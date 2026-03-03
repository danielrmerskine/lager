# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
import json
import queue
import threading
import time
import uuid
from datetime import datetime, timezone

from box_manager import get_box_manager


def _now_iso():
    """Return current UTC time as an ISO-style string matching SQLite datetime()."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


class RunRecord:
    """Tracks a single script execution run."""

    def __init__(self, run_id, box_id, script_name):
        self.run_id = run_id
        self.box_id = box_id
        self.script_name = script_name
        self.status = 'running'  # running | completed | failed | cancelled
        self.exit_code = None
        self.started_at = _now_iso()
        self.stopped_at = None
        self._start_epoch = time.time()
        self.output_lines = []  # full log for results page
        self.queue = queue.Queue()  # live queue for SSE streaming
        self._cancel = threading.Event()

    @property
    def duration(self):
        if self.stopped_at:
            try:
                start = datetime.strptime(self.started_at, '%Y-%m-%d %H:%M:%S')
                end = datetime.strptime(self.stopped_at, '%Y-%m-%d %H:%M:%S')
                return round((end - start).total_seconds(), 1)
            except (ValueError, TypeError):
                return 0
        return round(time.time() - self._start_epoch, 1)

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def to_dict(self):
        return {
            'run_id': self.run_id,
            'box_id': self.box_id,
            'script_name': self.script_name,
            'status': self.status,
            'exit_code': self.exit_code,
            'started_at': self.started_at,
            'stopped_at': self.stopped_at,
            'duration': self.duration,
            'stdout': '\n'.join(
                ol['line'] for ol in self.output_lines if ol['type'] == 'stdout'
            ),
            'stderr': '\n'.join(
                ol['line'] for ol in self.output_lines if ol['type'] == 'stderr'
            ),
        }


class SuiteRecord:
    """Tracks a suite of scripts executed sequentially."""

    def __init__(self, suite_id, box_id, script_names):
        self.suite_id = suite_id
        self.box_id = box_id
        self.script_names = list(script_names)
        self.status = 'running'  # running | completed | failed | cancelled
        self.started_at = _now_iso()
        self.stopped_at = None
        self._start_epoch = time.time()
        self.results = []  # list of {name, run_id, status, exit_code}
        self.queue = queue.Queue()  # live queue for SSE streaming
        self._cancel = threading.Event()

    @property
    def duration(self):
        if self.stopped_at:
            try:
                start = datetime.strptime(self.started_at, '%Y-%m-%d %H:%M:%S')
                end = datetime.strptime(self.stopped_at, '%Y-%m-%d %H:%M:%S')
                return round((end - start).total_seconds(), 1)
            except (ValueError, TypeError):
                return 0
        return round(time.time() - self._start_epoch, 1)

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def to_dict(self):
        return {
            'suite_id': self.suite_id,
            'box_id': self.box_id,
            'script_names': self.script_names,
            'status': self.status,
            'started_at': self.started_at,
            'stopped_at': self.stopped_at,
            'duration': self.duration,
            'results': list(self.results),
        }


# In-memory store of all runs and suites
_runs = {}
_runs_lock = threading.Lock()

_suites = {}
_suites_lock = threading.Lock()


def get_run(run_id):
    with _runs_lock:
        return _runs.get(run_id)


def get_all_runs():
    with _runs_lock:
        results = [
            r.to_dict() if isinstance(r, RunRecord) else r
            for r in _runs.values()
        ]
    results.sort(key=lambda r: r.get('started_at', ''), reverse=True)
    return results


def get_suite(suite_id):
    with _suites_lock:
        return _suites.get(suite_id)


def get_all_suites():
    with _suites_lock:
        results = [
            s.to_dict() if isinstance(s, SuiteRecord) else s
            for s in _suites.values()
        ]
    results.sort(key=lambda s: s.get('started_at', ''), reverse=True)
    return results


def start_run(box_id, script_content, script_name='script.py'):
    """Start a script execution on a remote box. Returns run_id."""
    run_id = str(uuid.uuid4())[:8]
    record = RunRecord(run_id, box_id, script_name)

    with _runs_lock:
        _runs[run_id] = record

    thread = threading.Thread(
        target=_execute_run,
        args=(record, script_content),
        daemon=True,
    )
    thread.start()
    return run_id


def start_suite_run(box_id, script_names):
    """Start sequential execution of multiple scripts. Returns suite_id."""
    suite_id = str(uuid.uuid4())[:8]
    suite = SuiteRecord(suite_id, box_id, script_names)

    with _suites_lock:
        _suites[suite_id] = suite

    thread = threading.Thread(
        target=_execute_suite,
        args=(suite,),
        daemon=True,
    )
    thread.start()
    return suite_id


def _emit(record, msg_type, line=''):
    """Push a message to both the live queue and the persistent log."""
    record.output_lines.append({'type': msg_type, 'line': line})
    record.queue.put({'type': msg_type, 'line': line})


def _suite_emit(suite, event_type, data):
    """Push a suite SSE event to the live queue."""
    suite.queue.put({'event': event_type, 'data': data})


def _execute_suite(suite):
    """Run scripts sequentially on a box, forwarding output to suite SSE."""
    import script_store

    for idx, script_name in enumerate(suite.script_names):
        if suite.cancelled:
            suite.status = 'cancelled'
            suite.stopped_at = _now_iso()
            _suite_emit(suite, 'suite_done', {
                'status': 'cancelled',
                'results': suite.results,
            })
            return

        content = script_store.get_script_content(script_name)
        if content is None:
            _suite_emit(suite, 'script_start', {'index': idx, 'name': script_name})
            _suite_emit(suite, 'script_end', {
                'index': idx,
                'name': script_name,
                'status': 'failed',
                'exit_code': 1,
            })
            suite.results.append({
                'name': script_name,
                'run_id': None,
                'status': 'failed',
                'exit_code': 1,
            })
            continue

        # Start individual run
        _suite_emit(suite, 'script_start', {'index': idx, 'name': script_name})

        run_id = start_run(suite.box_id, content, script_name)
        record = get_run(run_id)

        # Forward output from run to suite SSE
        last_line_idx = 0
        while True:
            if suite.cancelled:
                record.cancel()
                break

            # Forward any new output lines
            current_lines = record.output_lines[last_line_idx:]
            for ol in current_lines:
                if ol['type'] in ('stdout', 'stderr'):
                    _suite_emit(suite, 'script_output', {
                        'index': idx,
                        'name': script_name,
                        'output': ol,
                    })
                last_line_idx += 1

            # Check if run is done
            if record.status != 'running':
                # Forward any remaining lines
                remaining = record.output_lines[last_line_idx:]
                for ol in remaining:
                    if ol['type'] in ('stdout', 'stderr'):
                        _suite_emit(suite, 'script_output', {
                            'index': idx,
                            'name': script_name,
                            'output': ol,
                        })
                break

            time.sleep(0.2)

        _suite_emit(suite, 'script_end', {
            'index': idx,
            'name': script_name,
            'status': record.status,
            'exit_code': record.exit_code,
        })
        suite.results.append({
            'name': script_name,
            'run_id': run_id,
            'status': record.status,
            'exit_code': record.exit_code,
        })

    # Determine overall status
    if suite.cancelled:
        suite.status = 'cancelled'
    elif all(r['status'] == 'completed' for r in suite.results):
        suite.status = 'completed'
    else:
        suite.status = 'failed'

    suite.stopped_at = _now_iso()
    _suite_emit(suite, 'suite_done', {
        'status': suite.status,
        'results': suite.results,
    })


def _execute_run(record, script_content):
    """Run a script on a remote box via SSH + docker.

    Pattern follows deploy_and_test.sh:
      1. SSH to box
      2. Write script to /tmp on remote host
      3. docker cp into container
      4. docker exec python <script>
      5. Stream stdout/stderr line by line
      6. Cleanup
    """
    manager = get_box_manager()
    box = manager.get_box(record.box_id)
    if not box:
        _emit(record, 'stderr', f'Unknown box: {record.box_id}')
        record.status = 'failed'
        record.exit_code = 1
        record.stopped_at = _now_iso()
        _emit(record, 'done', '')
        return

    container = box.get('container', 'lager')
    remote_script = f'/tmp/lager_run_{record.run_id}.py'

    client = None
    try:
        _emit(record, 'stdout', f'Connecting to {box["ip"]}...')
        client = manager.get_ssh_client(record.box_id)

        if record.cancelled:
            _finish(record, 'cancelled', -1)
            return

        # Step 1: Find container
        _emit(record, 'stdout', f'Finding container "{container}"...')
        _, stdout, _ = client.exec_command(
            f'docker ps -q -f name=^{container}$', timeout=10
        )
        container_id = stdout.read().decode().strip()
        if not container_id:
            _emit(record, 'stderr', f'Container "{container}" not found or not running')
            _finish(record, 'failed', 1)
            return

        # Step 2: Upload script via sftp + docker cp
        _emit(record, 'stdout', 'Uploading script...')
        sftp = client.open_sftp()
        with sftp.file(remote_script, 'w') as f:
            f.write(script_content)
        sftp.close()

        client.exec_command(f'docker cp {remote_script} {container_id}:{remote_script}')
        time.sleep(0.5)  # let docker cp finish

        if record.cancelled:
            _cleanup(client, container_id, remote_script)
            _finish(record, 'cancelled', -1)
            return

        # Step 3: Execute inside container, stream output
        _emit(record, 'stdout', 'Running script...')
        _emit(record, 'stdout', '---')

        # Detect layout to set PYTHONPATH
        _, stdout_layout, _ = client.exec_command(
            f'docker exec {container_id} bash -c "echo \\$PYTHONPATH"', timeout=10
        )
        pythonpath = stdout_layout.read().decode().strip()
        env_prefix = f'-e PYTHONPATH={pythonpath}' if pythonpath else ''

        transport = client.get_transport()
        channel = transport.open_session()
        channel.exec_command(
            f'docker exec {env_prefix} {container_id} python {remote_script} 2>&1'
        )

        # Stream output line by line
        buf = ''
        while not channel.exit_status_ready() or channel.recv_ready():
            if record.cancelled:
                channel.close()
                _cleanup(client, container_id, remote_script)
                _finish(record, 'cancelled', -1)
                return

            if channel.recv_ready():
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                buf += chunk
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    _emit(record, 'stdout', line)
            else:
                time.sleep(0.1)

        # Flush remaining buffer
        if buf.strip():
            _emit(record, 'stdout', buf.strip())

        exit_code = channel.recv_exit_status()
        channel.close()

        _emit(record, 'stdout', '---')

        # Step 4: Cleanup
        _cleanup(client, container_id, remote_script)

        status = 'completed' if exit_code == 0 else 'failed'
        _finish(record, status, exit_code)

    except Exception as e:
        _emit(record, 'stderr', f'Error: {e}')
        _finish(record, 'failed', 1)
    finally:
        if client:
            client.close()


def _cleanup(client, container_id, remote_script):
    """Remove the script from container and host."""
    try:
        client.exec_command(f'docker exec {container_id} rm -f {remote_script}')
        client.exec_command(f'rm -f {remote_script}')
    except Exception:
        pass


def _finish(record, status, exit_code):
    record.status = status
    record.exit_code = exit_code
    record.stopped_at = _now_iso()
    _emit(record, 'done', '')


def stream_output(run_id):
    """Generator yielding SSE-formatted lines for a run. Blocks until done."""
    record = get_run(run_id)
    if not record:
        yield f'data: {{"type": "error", "line": "Unknown run: {run_id}"}}\n\n'
        return

    while True:
        try:
            msg = record.queue.get(timeout=30)
        except queue.Empty:
            # Send keepalive
            yield ': keepalive\n\n'
            continue

        yield f'data: {json.dumps(msg)}\n\n'

        if msg['type'] == 'done':
            yield f'data: {json.dumps({"type": "exit_code", "exit_code": record.exit_code})}\n\n'
            break


def stream_suite_output(suite_id):
    """Generator yielding SSE-formatted events for a suite. Blocks until done."""
    suite = get_suite(suite_id)
    if not suite:
        yield f'data: {json.dumps({"event": "error", "data": {"message": "Unknown suite"}})}\n\n'
        return

    while True:
        try:
            msg = suite.queue.get(timeout=30)
        except queue.Empty:
            yield ': keepalive\n\n'
            continue

        yield f'data: {json.dumps(msg)}\n\n'

        if msg['event'] == 'suite_done':
            break
