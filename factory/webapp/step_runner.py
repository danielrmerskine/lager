# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Interactive step execution engine for station runs.

Manages SSH sessions to boxes, parsing stdout for factory protocol events
and bridging user responses from WebSocket to script stdin.
"""

import json
import os
import queue
import threading
import time

from box_manager import get_box_manager
from box_data_client import BoxDataClient

# STX prefix for factory protocol messages on stdout
_FACTORY_PREFIX = '\x02FACTORY:'

# Active sessions keyed by run_id
_sessions = {}
_sessions_lock = threading.Lock()


class StepRunSession:
    """Tracks an interactive station run session."""

    def __init__(self, run_id, station_id, box_id):
        self.run_id = run_id
        self.station_id = station_id
        self.box_id = box_id
        self.status = 'starting'
        self.events = []
        self.stdout_lines = []
        self.stderr_lines = []
        self.to_client = queue.Queue()
        self.from_client = queue.Queue()
        self._cancel = threading.Event()
        self._channel = None

    def send_to_script(self, response_dict):
        """Write user response to script's stdin via SSH channel."""
        if self._channel and not self._channel.closed:
            msg = json.dumps(response_dict) + '\n'
            self._channel.sendall(msg.encode())

    def cancel(self):
        self._cancel.set()
        if self._channel and not self._channel.closed:
            self._channel.close()


def start_session(run_id, station_id, box_id, scripts=None):
    """Create a new session and start execution in a background thread.

    Args:
        scripts: Pre-fetched list of station script dicts. Required to avoid
                 Flask context errors when the daemon thread tries to query
                 the database.
    """
    session = StepRunSession(run_id, station_id, box_id)
    session._scripts = scripts
    with _sessions_lock:
        _sessions[run_id] = session

    thread = threading.Thread(
        target=_execute_step_run,
        args=(session,),
        daemon=True,
    )
    thread.start()
    return session


def get_session(run_id):
    with _sessions_lock:
        return _sessions.get(run_id)


def cleanup_session(run_id):
    with _sessions_lock:
        _sessions.pop(run_id, None)


def _execute_step_run(session):
    """Run station scripts on the box with interactive stdin/stdout."""
    manager = get_box_manager()
    box = manager.get_box(session.box_id)
    if not box:
        session.to_client.put({
            'type': 'lager-log', 'file': 'stderr',
            'content': f'Unknown box: {session.box_id}',
        })
        _finish_session(session, 'failed')
        return

    container = box.get('container', 'lager')
    scripts = session._scripts
    if not scripts:
        session.to_client.put({
            'type': 'lager-log', 'file': 'stderr',
            'content': 'No scripts in station',
        })
        _finish_session(session, 'failed')
        return

    client = None
    try:
        session.status = 'running'
        session.to_client.put({
            'type': 'lager-log', 'file': 'stdout',
            'content': f'Connecting to {box["ip"]}...',
        })

        client = manager.get_ssh_client(session.box_id)

        if session._cancel.is_set():
            _finish_session(session, 'cancelled')
            return

        # Find container
        _, stdout, _ = client.exec_command(
            f'docker ps -q -f name=^{container}$', timeout=10
        )
        container_id = stdout.read().decode().strip()
        if not container_id:
            session.to_client.put({
                'type': 'lager-log', 'file': 'stderr',
                'content': f'Container "{container}" not found or not running',
            })
            _finish_session(session, 'failed')
            return

        # Upload factory library + scripts via SFTP
        sftp = client.open_sftp()

        # Upload step_lib/factory.py as /tmp/factory.py (so scripts can
        # ``from factory import Step``)
        factory_lib_path = os.path.join(
            os.path.dirname(__file__), 'step_lib', 'factory.py'
        )
        with open(factory_lib_path, 'r') as f:
            factory_lib_content = f.read()
        sftp.file('/tmp/lager_factory_lib.py', 'w').write(factory_lib_content)

        # Upload all station scripts
        main_script = None
        for script in scripts:
            remote_name = f'/tmp/lager_station_{session.run_id}_{script["filename"]}'
            content = script['content']
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            with sftp.file(remote_name, 'w') as f:
                f.write(content)
            if main_script is None:
                main_script = remote_name

        sftp.close()

        # Docker cp files into the container
        client.exec_command(
            f'docker cp /tmp/lager_factory_lib.py '
            f'{container_id}:/tmp/factory.py'
        )
        for script in scripts:
            remote_name = f'/tmp/lager_station_{session.run_id}_{script["filename"]}'
            container_dest = f'/tmp/{script["filename"]}'
            client.exec_command(
                f'docker cp {remote_name} {container_id}:{container_dest}'
            )
        time.sleep(0.5)

        if session._cancel.is_set():
            _cleanup(client, container_id, session.run_id, scripts)
            _finish_session(session, 'cancelled')
            return

        # Detect PYTHONPATH
        _, stdout_pp, _ = client.exec_command(
            f'docker exec {container_id} bash -c "echo \\$PYTHONPATH"',
            timeout=10,
        )
        pythonpath = stdout_pp.read().decode().strip()
        env_parts = []
        if pythonpath:
            env_parts.append(f'-e PYTHONPATH=/tmp:{pythonpath}')
        else:
            env_parts.append('-e PYTHONPATH=/tmp')
        env_prefix = ' '.join(env_parts)

        # Determine main script -- first script with a STEPS list, or first script
        main_filename = scripts[0]['filename']
        for script in scripts:
            content = script['content']
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            if 'STEPS' in content:
                main_filename = script['filename']
                break

        # Check if main script has STEPS but no factory.run() call
        main_content = None
        for script in scripts:
            if script['filename'] == main_filename:
                main_content = script['content']
                if isinstance(main_content, bytes):
                    main_content = main_content.decode('utf-8', errors='replace')
                break

        needs_wrapper = (
            main_content and 'STEPS' in main_content
            and 'factory.run(' not in main_content
            and 'run(STEPS)' not in main_content
        )

        wrapper_filename = None
        if needs_wrapper:
            wrapper_module = main_filename.replace('.py', '')
            wrapper_content = (
                f'import sys; sys.path.insert(0, "/tmp")\n'
                f'import {wrapper_module}\n'
                f'from factory import run\n'
                f'if hasattr({wrapper_module}, "STEPS"):\n'
                f'    run({wrapper_module}.STEPS)\n'
            )
            wrapper_filename = f'_lager_wrapper_{session.run_id}.py'
            # Write wrapper to host via SFTP, then docker cp into container
            remote_wrapper = f'/tmp/{wrapper_filename}'
            sftp2 = client.open_sftp()
            with sftp2.file(remote_wrapper, 'w') as f:
                f.write(wrapper_content)
            sftp2.close()
            client.exec_command(
                f'docker cp {remote_wrapper} {container_id}:/tmp/{wrapper_filename}'
            )
            time.sleep(0.3)
            main_filename = wrapper_filename

        # Execute with -i flag for interactive stdin
        transport = client.get_transport()
        channel = transport.open_session()
        session._channel = channel

        cmd = (
            f'docker exec -i {env_prefix} {container_id} '
            f'python /tmp/{main_filename}'
        )
        channel.exec_command(cmd)

        session.to_client.put({
            'type': 'lager-log', 'file': 'stdout',
            'content': 'Running station scripts...',
        })

        # Read loop: parse stdout for factory events
        buf = ''
        stderr_buf = ''
        while not channel.exit_status_ready() or channel.recv_ready():
            if session._cancel.is_set():
                channel.close()
                _cleanup(client, container_id, session.run_id, scripts)
                _finish_session(session, 'cancelled')
                return

            # Always forward pending user responses to the script's
            # stdin -- do this every iteration so interactive prompts
            # are answered promptly even while output is being read.
            try:
                resp = session.from_client.get_nowait()
                session.send_to_script(resp)
            except queue.Empty:
                pass

            has_data = False
            if channel.recv_ready():
                has_data = True
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                buf += chunk
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    _process_line(session, line)
            if channel.recv_stderr_ready():
                has_data = True
                stderr_chunk = channel.recv_stderr(4096).decode('utf-8', errors='replace')
                stderr_buf += stderr_chunk
                while '\n' in stderr_buf:
                    line, stderr_buf = stderr_buf.split('\n', 1)
                    session.stderr_lines.append(line)
                    session.to_client.put({
                        'type': 'lager-log', 'file': 'stderr', 'content': line,
                    })
            if not has_data:
                time.sleep(0.05)

        # Flush remaining buffer
        if buf.strip():
            _process_line(session, buf.strip())
        if stderr_buf.strip():
            session.stderr_lines.append(stderr_buf.strip())
            session.to_client.put({
                'type': 'lager-log', 'file': 'stderr',
                'content': stderr_buf.strip(),
            })

        exit_code = channel.recv_exit_status()
        channel.close()
        session._channel = None

        # Cleanup
        _cleanup(client, container_id, session.run_id, scripts)

        status = 'completed' if exit_code == 0 else 'failed'
        _finish_session(session, status)

    except Exception as e:
        session.to_client.put({
            'type': 'lager-log', 'file': 'stderr',
            'content': f'Error: {e}',
        })
        _finish_session(session, 'failed')
    finally:
        if client:
            client.close()


def _process_line(session, line):
    """Parse a single stdout line, routing factory events vs regular output."""
    if line.startswith(_FACTORY_PREFIX):
        json_str = line[len(_FACTORY_PREFIX):]
        try:
            event = json.loads(json_str)
            session.events.append(event)
            session.to_client.put(event)
        except json.JSONDecodeError:
            # Malformed factory message -- treat as regular output
            session.stdout_lines.append(line)
            session.to_client.put({
                'type': 'lager-log', 'file': 'stdout', 'content': line,
            })
    else:
        session.stdout_lines.append(line)
        session.to_client.put({
            'type': 'lager-log', 'file': 'stdout', 'content': line,
        })


def _finish_session(session, status):
    """Mark session complete, save to box API, and push terminal event."""
    session.status = status
    # If we haven't already sent a factory-complete event, send one
    has_complete = any(
        e.get('type') == 'lager-factory-complete' for e in session.events
    )
    if not has_complete:
        complete_event = {
            'type': 'lager-factory-complete',
            'result': status == 'completed',
            'success': 0,
            'failure': 0,
            'failed_step': '',
        }
        session.events.append(complete_event)
        session.to_client.put(complete_event)

    # Persist results to box API so data survives browser tab close
    try:
        from datetime import datetime, timezone
        complete = next(
            (e for e in session.events
             if e.get('type') == 'lager-factory-complete'),
            {},
        )
        stopped_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        manager = get_box_manager()
        box = manager.get_box(session.box_id)
        if box:
            client = BoxDataClient(box['ip'])
            client.update_station_run(
                session.run_id,
                status=status,
                event_log=json.dumps(session.events),
                stdout='\n'.join(session.stdout_lines),
                stderr='\n'.join(session.stderr_lines),
                success=complete.get('success', 0),
                failure=complete.get('failure', 0),
                failed_step=complete.get('failed_step', ''),
                stopped_at=stopped_at,
            )
    except Exception:
        pass


def _cleanup(client, container_id, run_id, scripts):
    """Remove uploaded files from container and host."""
    try:
        client.exec_command(
            f'docker exec {container_id} rm -f /tmp/factory.py'
        )
        client.exec_command(f'rm -f /tmp/lager_factory_lib.py')
        for script in scripts:
            fname = script['filename']
            client.exec_command(
                f'docker exec {container_id} rm -f /tmp/{fname}'
            )
            client.exec_command(
                f'rm -f /tmp/lager_station_{run_id}_{fname}'
            )
        # Clean up wrapper if it exists
        client.exec_command(
            f'docker exec {container_id} rm -f /tmp/_lager_wrapper_{run_id}.py'
        )
    except Exception:
        pass
