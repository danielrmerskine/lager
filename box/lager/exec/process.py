# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
lager.exec.process - Process Output Streaming and Management

Utilities for managing process execution, output streaming, and cleanup.

Migrated from gateway/controller/controller/application/views/run.py (legacy, removed)
"""

import tempfile
import subprocess
import select
import time
import logging
import functools

logger = logging.getLogger(__name__)

KEEPALIVE_TIME = 20  # seconds


def make_output_channel(cleanup_fns):
    """
    Create a temporary file for output channel.

    The output channel is used to communicate between processes and stream
    additional data beyond stdout/stderr.

    Args:
        cleanup_fns: Set of cleanup functions to add the close function to

    Returns:
        tempfile.NamedTemporaryFile: Output channel file object
    """
    output_channel = tempfile.NamedTemporaryFile('w+b', 0)
    add_cleanup_fn(cleanup_fns, output_channel.close)
    return output_channel


def add_cleanup_fn(cleanup_fns, fn, *args, **kwargs):
    """
    Add a cleanup function to be called later.

    Args:
        cleanup_fns: Set of cleanup functions
        fn: Function to call during cleanup
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function

    Returns:
        set: Updated cleanup_fns set
    """
    cleanup_fns.add(functools.partial(fn, *args, **kwargs))
    return cleanup_fns


def do_cleanup(cleanup_fns):
    """
    Execute all cleanup functions.

    Args:
        cleanup_fns: Set of cleanup functions to execute
    """
    for cleanup_fn in cleanup_fns:
        try:
            cleanup_fn()
        except BaseException as exc:
            logger.exception('Cleanup function failed', exc_info=exc)
    cleanup_fns.clear()


def terminate_process(proc):
    """
    Terminate a process gracefully, or kill it if necessary.

    Attempts SIGTERM first, waits up to 2 seconds, then sends SIGKILL if needed.

    Args:
        proc: subprocess.Popen object

    Returns:
        int: Process return code, or -1 if killed
    """
    proc.terminate()
    try:
        return proc.wait(2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(2)
        return -1


def emit(fileno, chunk):
    """
    Emit a chunk of data with a header.

    Format: "<fileno> <length> <chunk>"

    Args:
        fileno: File descriptor number (1=stdout, 2=stderr, 3=output_channel, 0=keepalive)
        chunk: Data chunk to emit

    Yields:
        bytes: Header and chunk data
    """
    header = f'{fileno} {len(chunk)} '.encode()
    yield header
    if chunk:
        yield chunk


def stream_process_output(proc, output_channel, cleanup_fns):
    """
    Stream output from a running process.

    Reads from stdout, stderr, and output_channel, multiplexes them with
    headers, and yields chunks for HTTP streaming. Also sends keepalive
    messages every KEEPALIVE_TIME seconds.

    Args:
        proc: subprocess.Popen object
        output_channel: Additional output channel file object
        cleanup_fns: Set of cleanup functions to call when done

    Yields:
        bytes: Formatted output chunks with headers

    Format:
        Each chunk is prefixed with: "<fileno> <length> <data>"
        - fileno 0: Keepalive (empty chunk)
        - fileno 1: stdout
        - fileno 2: stderr
        - fileno 3: output_channel
        - Final line: "- <len> <returncode>"
    """
    fileno_map = {
        proc.stdout: 1,
        output_channel: 3,
    }
    # Only add stderr to map if it's a real file handle (not None when redirected to stdout)
    if proc.stderr is not None:
        fileno_map[proc.stderr] = 2

    try:
        readables = [proc.stdout, output_channel]
        if proc.stderr is not None:
            readables.append(proc.stderr)

        last_keepalive = time.time()

        while True:
            # Stop when only output_channel remains
            if readables == [output_channel]:
                break

            # Wait for readable data (0.1s timeout)
            rlist, _wlist, _xlist = select.select(readables, [], [], 0.1)

            # Read from each readable fd
            for readable in rlist:
                chunk = readable.read(1024)
                if chunk == b'':
                    # End of stream for this fd
                    if readable == output_channel:
                        continue  # Don't remove output_channel yet
                    readables.remove(readable)

                fileno = fileno_map[readable]
                yield from emit(fileno, chunk)

            # Send keepalive if needed
            now = time.time()
            if now - last_keepalive > KEEPALIVE_TIME:
                last_keepalive = now
                yield from emit(0, b'')

        # Process finished - get return code
        returncode = str(terminate_process(proc))

        # Read any remaining output channel data
        remaining = output_channel.read()
        yield from emit(fileno_map[output_channel], remaining)

        # Send final return code
        yield f'- {len(returncode)} {returncode}'.encode()

    except Exception as exc:
        logger.exception('stream_process_output failed', exc_info=exc)
    finally:
        do_cleanup(cleanup_fns)


# Export cleanup functions for external use
cleanup_functions = {
    'add': add_cleanup_fn,
    'do': do_cleanup,
}
