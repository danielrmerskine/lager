# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
J-Link interaction library

This module provides a Python interface for communicating with J-Link
debug probes using the J-Link Commander (JLinkExe).
"""

import os
import time
from contextlib import closing, contextmanager
import pexpect
from pexpect import replwrap


# JLinkExe paths (checked in order)
JLINK_EXE_PATHS = [
    '/tmp/lager-jlink-bin/JLinkExe',  # Symlinks to /opt/SEGGER (most common)
    '/opt/SEGGER/JLink_V794e/JLinkExe',  # Direct path on newer boxes
    '/home/www-data/third_party/jlink/JLinkExe',
    '/home/www-data/third_party/JLink_V884/JLinkExe',
    '/home/www-data/third_party/JLink_Linux_V794a_x86_64/JLinkExe',
    '/usr/bin/JLinkExe',
]


def get_jlink_exe_path():
    """Find JLinkExe executable, return None if not found."""
    for path in JLINK_EXE_PATHS:
        if os.path.exists(path):
            return path
    return None


@contextmanager
def commander(args, script_file=None):
    """
    Context manager for J-Link Commander REPL wrapper

    Args:
        args: Command-line arguments for JLinkExe
        script_file: Optional path to J-Link script file (.JLinkScript)

    Yields:
        REPLWrapper instance for interacting with J-Link Commander

    Example:
        with commander(['-device', 'NRF52840_XXAA']) as jl:
            output = jl.run_command('connect')

        # With script file:
        with commander(['-device', 'NRF52840_XXAA'], script_file='/tmp/init.JLinkScript') as jl:
            output = jl.run_command('connect')
    """
    jlink_exe = get_jlink_exe_path()
    if not jlink_exe:
        raise Exception('JLinkExe not found')

    full_args = list(args)
    if script_file and os.path.exists(script_file):
        full_args.extend(['-JLinkScriptFile', script_file])

    child = pexpect.spawn(jlink_exe, full_args, encoding='utf-8')
    with closing(child):
        try:
            repl = replwrap.REPLWrapper(child, "J-Link>", None)
            yield repl
            repl.run_command('q')
        except pexpect.exceptions.EOF:
            pass


class JLink:
    """
    Class for communicating with J-Link debug probes
    """

    def __init__(self, cmdline, script_file=None):
        """
        Initialize J-Link interface from command line

        Args:
            cmdline: Command line arguments list from running process
            script_file: Optional path to J-Link script file (.JLinkScript)
        """
        args_start = cmdline.index('-device')
        args = cmdline[args_start:]
        if not args[-1]:
            args = args[:-1]
        speed_idx = args.index('-speed')
        args = args[:speed_idx + 2]
        self.args = args
        self.script_file = script_file

    def erase(self, start_addr, length, *, close=True):
        """
        Erase flash memory

        Args:
            start_addr: Starting address for erase
            length: Number of bytes to erase
            close: Whether to close connection after operation (unused for J-Link)

        Yields:
            Output from J-Link commands
        """
        with commander(self.args, script_file=self.script_file) as jl:
            yield jl.run_command('connect')
            yield jl.run_command(f'erase {hex(start_addr)} {hex(start_addr + length - 1)}')

    def chip_erase(self, *, close=True):
        """
        Perform full chip erase

        Args:
            close: Whether to close connection after operation (unused for J-Link)

        Yields:
            Output from J-Link commands
        """
        with commander(self.args, script_file=self.script_file) as jl:
            yield jl.run_command('connect')
            # Full chip erase - no parameters erases entire chip
            yield jl.run_command('erase')

    def read_memory(self, address, length, *, close=True):
        """
        Read memory from device

        Args:
            address: Starting memory address (int)
            length: Number of bytes to read
            close: Whether to close connection after operation (unused for J-Link)

        Returns:
            bytes object containing the memory data
        """
        import re
        memory_data = []

        with commander(self.args, script_file=self.script_file) as jl:
            jl.run_command('connect')
            # J-Link Commander mem8 syntax: mem8 address count
            output = jl.run_command(f'mem8 {hex(address)} {length}')

            # Parse output format: "00000000 = FF FF FF FF ..."
            # Each line contains one address worth of data
            for line in output.split('\n'):
                if '=' in line:
                    # Split on '=' and take the right side (the memory bytes)
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        data_part = parts[1]
                        # Extract hex bytes (2-character hex patterns)
                        hex_bytes = re.findall(r'([0-9A-Fa-f]{2})', data_part)
                        for hex_byte in hex_bytes:
                            memory_data.append(int(hex_byte, 16))

        # Trim to requested length
        return bytes(memory_data[:length])

    def flash(self, files, preverify=False, verify=False, *, close=True):
        """
        Flash firmware to device

        Args:
            files: Tuple of (hexfiles, binfiles, elffiles) to program
            preverify: Whether to verify before flashing (unused for J-Link)
            verify: Whether to verify after flashing (unused for J-Link)
            close: Whether to close connection after operation (unused for J-Link)

        Yields:
            Output from J-Link commands
        """
        (hexfiles, binfiles, elffiles) = files
        with commander(self.args, script_file=self.script_file) as jl:
            # Yield connect output to show device discovery details
            yield jl.run_command('connect')

            # Yield loadfile output
            for file in hexfiles:
                yield jl.run_command(f'loadfile {file}')
            for (file, address) in binfiles:
                yield jl.run_command(f'loadfile {file} {hex(address)}')
            for file in elffiles:
                yield jl.run_command(f'loadfile {file}')

    def reset(self, halt, *, close=True):
        """
        Reset the device

        Args:
            halt: Whether to halt after reset
            close: Whether to close connection after operation (unused for J-Link)

        Yields:
            Output from J-Link commands
        """
        with commander(self.args, script_file=self.script_file) as jl:
            yield jl.run_command('connect')
            if halt:
                yield jl.run_command('r')
                yield jl.run_command('h')
            else:
                # rnh == reset no halt
                yield jl.run_command('rnh')

    def run(self, *, close=True):
        """
        Run the device (reset without halt)

        Args:
            close: Whether to close connection after operation (unused for J-Link)

        Yields:
            Output from J-Link commands
        """
        yield from self.reset(halt=False)