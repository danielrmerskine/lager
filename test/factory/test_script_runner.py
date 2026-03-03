# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/script_runner.py."""

import json
import queue
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_module_state():
    """Clear the module-level _runs and _suites dicts in script_runner."""
    import script_runner
    with script_runner._runs_lock:
        script_runner._runs.clear()
    with script_runner._suites_lock:
        script_runner._suites.clear()


@pytest.fixture(autouse=True)
def clean_runner_state():
    """Ensure _runs and _suites are empty before and after every test."""
    _clear_module_state()
    yield
    _clear_module_state()


def _make_mock_channel(output_lines=None, exit_code=0, slow=False):
    """Build a mock paramiko channel that yields lines then exits.

    Args:
        output_lines: list of bytes lines (each WITHOUT trailing newline).
        exit_code: integer exit code to return.
        slow: if True, simulate a delay between recv calls.
    """
    if output_lines is None:
        output_lines = []

    channel = MagicMock()
    # Build the full output as bytes with newlines
    full_output = b'\n'.join(output_lines) + (b'\n' if output_lines else b'')
    _recv_chunks = [full_output] if full_output else []
    _recv_idx = [0]

    def _exit_status_ready():
        return _recv_idx[0] >= len(_recv_chunks)

    def _recv_ready():
        return _recv_idx[0] < len(_recv_chunks)

    def _recv(size):
        if _recv_idx[0] < len(_recv_chunks):
            data = _recv_chunks[_recv_idx[0]]
            _recv_idx[0] += 1
            return data
        return b''

    channel.exit_status_ready = _exit_status_ready
    channel.recv_ready = _recv_ready
    channel.recv = _recv
    channel.recv_exit_status.return_value = exit_code
    channel.close = MagicMock()
    return channel


def _make_mock_ssh_client(
    container_id='abc123',
    channel=None,
    pythonpath='',
    sftp_ok=True,
):
    """Build a mock paramiko SSHClient with exec_command/open_sftp/get_transport."""
    client = MagicMock()

    def _exec_command(cmd, timeout=None):
        stdin = MagicMock()
        stdout = MagicMock()
        stderr = MagicMock()

        if 'docker ps -q' in cmd:
            stdout.read.return_value = (container_id or '').encode()
        elif 'echo' in cmd and 'PYTHONPATH' in cmd:
            stdout.read.return_value = pythonpath.encode()
        else:
            stdout.read.return_value = b''

        return stdin, stdout, stderr

    client.exec_command = MagicMock(side_effect=_exec_command)

    # SFTP mock
    sftp = MagicMock()
    sftp.file.return_value.__enter__ = MagicMock(return_value=MagicMock())
    sftp.file.return_value.__exit__ = MagicMock(return_value=False)
    client.open_sftp.return_value = sftp

    # Transport / channel mock
    if channel is None:
        channel = _make_mock_channel(exit_code=0)
    transport = MagicMock()
    transport.open_session.return_value = channel
    client.get_transport.return_value = transport

    return client


# ===========================================================================
# RunRecord
# ===========================================================================

class TestRunRecordInit:

    def test_initial_state(self):
        """RunRecord initializes with correct defaults."""
        import script_runner
        rec = script_runner.RunRecord('abc12345', 'test-box', 'myscript.py')

        assert rec.run_id == 'abc12345'
        assert rec.box_id == 'test-box'
        assert rec.script_name == 'myscript.py'
        assert rec.status == 'running'
        assert rec.exit_code is None
        assert rec.stopped_at is None
        assert rec.output_lines == []
        assert isinstance(rec.queue, queue.Queue)
        assert rec.cancelled is False

    def test_started_at_format(self):
        """started_at is in '%Y-%m-%d %H:%M:%S' format."""
        import script_runner
        rec = script_runner.RunRecord('id1', 'box', 'script.py')

        # Should parse without error
        parsed = datetime.strptime(rec.started_at, '%Y-%m-%d %H:%M:%S')
        assert isinstance(parsed, datetime)

    def test_start_epoch_set(self):
        """_start_epoch is set close to the current time."""
        import script_runner
        before = time.time()
        rec = script_runner.RunRecord('id1', 'box', 'script.py')
        after = time.time()

        assert before <= rec._start_epoch <= after


class TestRunRecordToDict:

    def test_basic_fields(self):
        """to_dict returns all expected keys."""
        import script_runner
        rec = script_runner.RunRecord('r1', 'box-a', 'test.py')

        d = rec.to_dict()
        assert d['run_id'] == 'r1'
        assert d['box_id'] == 'box-a'
        assert d['script_name'] == 'test.py'
        assert d['status'] == 'running'
        assert d['exit_code'] is None
        assert d['stopped_at'] is None
        assert 'duration' in d
        assert 'stdout' in d
        assert 'stderr' in d

    def test_filters_stdout_only(self):
        """to_dict joins only stdout-type output lines into 'stdout'."""
        import script_runner
        rec = script_runner.RunRecord('r2', 'box', 's.py')
        rec.output_lines = [
            {'type': 'stdout', 'line': 'hello'},
            {'type': 'stderr', 'line': 'oops'},
            {'type': 'stdout', 'line': 'world'},
            {'type': 'done', 'line': ''},
        ]

        d = rec.to_dict()
        assert d['stdout'] == 'hello\nworld'
        assert d['stderr'] == 'oops'

    def test_empty_output(self):
        """to_dict handles empty output_lines."""
        import script_runner
        rec = script_runner.RunRecord('r3', 'box', 's.py')

        d = rec.to_dict()
        assert d['stdout'] == ''
        assert d['stderr'] == ''


class TestRunRecordDuration:

    def test_running_uses_epoch(self):
        """While running (stopped_at is None), duration uses wall clock from _start_epoch."""
        import script_runner
        rec = script_runner.RunRecord('r4', 'box', 's.py')
        rec._start_epoch = time.time() - 5.0  # pretend started 5s ago

        dur = rec.duration
        assert dur >= 4.9  # allow small float drift
        assert dur < 10.0

    def test_stopped_uses_timestamps(self):
        """When stopped, duration is computed from started_at/stopped_at strings."""
        import script_runner
        rec = script_runner.RunRecord('r5', 'box', 's.py')
        rec.started_at = '2025-01-01 10:00:00'
        rec.stopped_at = '2025-01-01 10:00:37'

        assert rec.duration == 37.0

    def test_bad_timestamps_return_zero(self):
        """If stopped_at/started_at are unparseable, duration returns 0."""
        import script_runner
        rec = script_runner.RunRecord('r6', 'box', 's.py')
        rec.started_at = 'not-a-date'
        rec.stopped_at = 'also-bad'

        assert rec.duration == 0

    def test_none_started_at_returns_zero(self):
        """If started_at is None but stopped_at is set, duration returns 0."""
        import script_runner
        rec = script_runner.RunRecord('r7', 'box', 's.py')
        rec.started_at = None
        rec.stopped_at = '2025-01-01 10:00:00'

        assert rec.duration == 0


class TestRunRecordCancel:

    def test_cancel_sets_flag(self):
        """cancel() sets the cancelled property to True."""
        import script_runner
        rec = script_runner.RunRecord('r8', 'box', 's.py')

        assert rec.cancelled is False
        rec.cancel()
        assert rec.cancelled is True

    def test_cancel_idempotent(self):
        """Calling cancel() multiple times is safe."""
        import script_runner
        rec = script_runner.RunRecord('r9', 'box', 's.py')
        rec.cancel()
        rec.cancel()
        assert rec.cancelled is True


# ===========================================================================
# SuiteRecord
# ===========================================================================

class TestSuiteRecordInit:

    def test_initial_state(self):
        """SuiteRecord initializes with correct defaults."""
        import script_runner
        suite = script_runner.SuiteRecord('sid1', 'box-1', ['a.py', 'b.py'])

        assert suite.suite_id == 'sid1'
        assert suite.box_id == 'box-1'
        assert suite.script_names == ['a.py', 'b.py']
        assert suite.status == 'running'
        assert suite.stopped_at is None
        assert suite.results == []
        assert isinstance(suite.queue, queue.Queue)
        assert suite.cancelled is False

    def test_script_names_is_a_copy(self):
        """script_names is a list copy, not a reference to the original."""
        import script_runner
        original = ['x.py', 'y.py']
        suite = script_runner.SuiteRecord('sid2', 'box', original)

        original.append('z.py')
        assert suite.script_names == ['x.py', 'y.py']


class TestSuiteRecordToDict:

    def test_basic_fields(self):
        """to_dict returns all expected keys."""
        import script_runner
        suite = script_runner.SuiteRecord('sid3', 'box', ['a.py'])

        d = suite.to_dict()
        assert d['suite_id'] == 'sid3'
        assert d['box_id'] == 'box'
        assert d['script_names'] == ['a.py']
        assert d['status'] == 'running'
        assert 'duration' in d
        assert d['results'] == []

    def test_results_is_copy(self):
        """to_dict returns a copy of results, not a reference."""
        import script_runner
        suite = script_runner.SuiteRecord('sid4', 'box', ['a.py'])
        suite.results.append({'name': 'a.py', 'status': 'completed'})

        d = suite.to_dict()
        d['results'].append({'name': 'extra', 'status': 'failed'})

        assert len(suite.results) == 1  # original unchanged


class TestSuiteRecordDuration:

    def test_running_uses_epoch(self):
        """While running, duration uses wall clock."""
        import script_runner
        suite = script_runner.SuiteRecord('sid5', 'box', [])
        suite._start_epoch = time.time() - 3.0

        assert suite.duration >= 2.9
        assert suite.duration < 10.0

    def test_stopped_uses_timestamps(self):
        """When stopped, duration uses started_at/stopped_at."""
        import script_runner
        suite = script_runner.SuiteRecord('sid6', 'box', [])
        suite.started_at = '2025-06-01 12:00:00'
        suite.stopped_at = '2025-06-01 12:01:30'

        assert suite.duration == 90.0


class TestSuiteRecordCancel:

    def test_cancel(self):
        """cancel() sets the cancelled flag."""
        import script_runner
        suite = script_runner.SuiteRecord('sid7', 'box', [])
        assert suite.cancelled is False
        suite.cancel()
        assert suite.cancelled is True


# ===========================================================================
# start_run
# ===========================================================================

class TestStartRun:

    def test_returns_8char_id(self, app):
        """start_run returns an 8-character run ID."""
        import script_runner

        with patch.object(script_runner, '_execute_run'):
            run_id = script_runner.start_run('test-box', 'print("hi")', 'test.py')

        assert isinstance(run_id, str)
        assert len(run_id) == 8

    def test_stores_in_runs_dict(self, app):
        """start_run stores the RunRecord in the _runs dict."""
        import script_runner

        with patch.object(script_runner, '_execute_run'):
            run_id = script_runner.start_run('test-box', 'code', 'my.py')

        rec = script_runner.get_run(run_id)
        assert rec is not None
        assert rec.box_id == 'test-box'
        assert rec.script_name == 'my.py'

    def test_default_script_name(self, app):
        """start_run defaults script_name to 'script.py'."""
        import script_runner

        with patch.object(script_runner, '_execute_run'):
            run_id = script_runner.start_run('test-box', 'code')

        rec = script_runner.get_run(run_id)
        assert rec.script_name == 'script.py'


# ===========================================================================
# get_run / get_all_runs
# ===========================================================================

class TestGetRun:

    def test_existing_run(self, app):
        """get_run returns a RunRecord for a known run_id."""
        import script_runner

        rec = script_runner.RunRecord('known-id', 'box', 's.py')
        with script_runner._runs_lock:
            script_runner._runs['known-id'] = rec

        result = script_runner.get_run('known-id')
        assert result is rec

    def test_unknown_run(self, app):
        """get_run returns None for an unknown run_id."""
        import script_runner
        assert script_runner.get_run('nonexistent') is None


class TestGetAllRuns:

    def test_returns_all_in_memory_runs(self, app):
        """get_all_runs returns both running and completed RunRecords."""
        import script_runner

        active_rec = script_runner.RunRecord('active01', 'box', 's.py')
        active_rec.started_at = '2025-06-01 12:01:00'
        done_rec = script_runner.RunRecord('done01', 'box', 's.py')
        done_rec.status = 'completed'
        done_rec.started_at = '2025-06-01 12:00:00'
        with script_runner._runs_lock:
            script_runner._runs['active01'] = active_rec
            script_runner._runs['done01'] = done_rec

        results = script_runner.get_all_runs()

        ids = [r['run_id'] for r in results]
        assert 'active01' in ids
        assert 'done01' in ids

    def test_sorted_desc_by_started_at(self, app):
        """Results are sorted by started_at descending (newest first)."""
        import script_runner

        rec1 = script_runner.RunRecord('old1', 'box', 's.py')
        rec1.started_at = '2025-01-01 01:00:00'
        rec2 = script_runner.RunRecord('new1', 'box', 's.py')
        rec2.started_at = '2025-12-31 23:00:00'
        with script_runner._runs_lock:
            script_runner._runs['old1'] = rec1
            script_runner._runs['new1'] = rec2

        results = script_runner.get_all_runs()

        assert results[0]['run_id'] == 'new1'
        assert results[1]['run_id'] == 'old1'

    def test_completed_runs_included(self, app):
        """Completed in-memory runs ARE included (they stay in _runs dict)."""
        import script_runner

        rec = script_runner.RunRecord('done1', 'box', 's.py')
        rec.status = 'completed'
        rec.started_at = '2025-06-01 12:00:00'
        with script_runner._runs_lock:
            script_runner._runs['done1'] = rec

        results = script_runner.get_all_runs()

        assert len(results) == 1
        assert results[0]['run_id'] == 'done1'


# ===========================================================================
# _execute_run (mocked SSH)
# ===========================================================================

class TestExecuteRun:

    def test_unknown_box_fails(self, app, mock_box_manager):
        """_execute_run marks the run as failed when box_id is unknown."""
        import script_runner

        rec = script_runner.RunRecord('unk1', 'no-such-box', 's.py')
        script_runner._execute_run(rec, 'print("hi")')

        assert rec.status == 'failed'
        assert rec.exit_code == 1
        assert rec.stopped_at is not None
        # Check that error message was emitted
        stderr_lines = [ol['line'] for ol in rec.output_lines if ol['type'] == 'stderr']
        assert any('Unknown box' in line for line in stderr_lines)

    def test_container_not_found(self, app, mock_box_manager):
        """_execute_run fails when docker ps returns empty (no container)."""
        import script_runner

        client = _make_mock_ssh_client(container_id='')
        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            rec = script_runner.RunRecord('cnt1', 'test-box', 's.py')
            script_runner._execute_run(rec, 'code')

        assert rec.status == 'failed'
        assert rec.exit_code == 1
        stderr_lines = [ol['line'] for ol in rec.output_lines if ol['type'] == 'stderr']
        assert any('not found' in line or 'not running' in line for line in stderr_lines)

    def test_success_exit_zero(self, app, mock_box_manager):
        """_execute_run marks run as completed when exit code is 0."""
        import script_runner

        channel = _make_mock_channel(
            output_lines=[b'hello', b'world'],
            exit_code=0,
        )
        client = _make_mock_ssh_client(container_id='ctr123', channel=channel)

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            rec = script_runner.RunRecord('ok1', 'test-box', 's.py')
            script_runner._execute_run(rec, 'print("hello")')

        assert rec.status == 'completed'
        assert rec.exit_code == 0
        assert rec.stopped_at is not None

    def test_failed_nonzero_exit(self, app, mock_box_manager):
        """_execute_run marks run as failed when exit code is nonzero."""
        import script_runner

        channel = _make_mock_channel(output_lines=[b'error!'], exit_code=1)
        client = _make_mock_ssh_client(container_id='ctr456', channel=channel)

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            rec = script_runner.RunRecord('fail1', 'test-box', 's.py')
            script_runner._execute_run(rec, 'raise Exception()')

        assert rec.status == 'failed'
        assert rec.exit_code == 1

    def test_cancel_before_start(self, app, mock_box_manager):
        """_execute_run exits with cancelled status if cancelled before SSH."""
        import script_runner

        client = _make_mock_ssh_client(container_id='ctr789')
        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            rec = script_runner.RunRecord('canc1', 'test-box', 's.py')
            rec.cancel()  # Cancel before execution starts
            script_runner._execute_run(rec, 'code')

        assert rec.status == 'cancelled'
        assert rec.exit_code == -1

    def test_cancel_during_execution(self, app, mock_box_manager):
        """_execute_run detects cancellation during the streaming loop."""
        import script_runner

        # Build a channel that blocks until cancelled
        channel = MagicMock()
        channel.exit_status_ready.return_value = False
        channel.recv_ready.return_value = False
        channel.recv_exit_status.return_value = 0
        channel.close = MagicMock()

        client = _make_mock_ssh_client(container_id='ctrABC', channel=channel)

        rec = script_runner.RunRecord('canc2', 'test-box', 's.py')

        # Schedule cancellation after a short delay
        def _delayed_cancel():
            time.sleep(0.3)
            rec.cancel()

        cancel_thread = threading.Thread(target=_delayed_cancel)
        cancel_thread.start()

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            script_runner._execute_run(rec, 'code')

        cancel_thread.join(timeout=5)

        assert rec.status == 'cancelled'
        assert rec.exit_code == -1

    def test_exception_caught(self, app, mock_box_manager):
        """_execute_run catches exceptions and marks the run as failed."""
        import script_runner

        with patch.object(
            mock_box_manager, 'get_ssh_client',
            side_effect=Exception('SSH connection refused'),
        ):
            rec = script_runner.RunRecord('exc1', 'test-box', 's.py')
            script_runner._execute_run(rec, 'code')

        assert rec.status == 'failed'
        assert rec.exit_code == 1
        stderr_lines = [ol['line'] for ol in rec.output_lines if ol['type'] == 'stderr']
        assert any('SSH connection refused' in line for line in stderr_lines)

    def test_output_lines_captured(self, app, mock_box_manager):
        """_execute_run captures stdout lines in output_lines."""
        import script_runner

        channel = _make_mock_channel(
            output_lines=[b'line1', b'line2', b'line3'],
            exit_code=0,
        )
        client = _make_mock_ssh_client(container_id='ctrOut', channel=channel)

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            rec = script_runner.RunRecord('out1', 'test-box', 's.py')
            script_runner._execute_run(rec, 'code')

        stdout_lines = [
            ol['line'] for ol in rec.output_lines if ol['type'] == 'stdout'
        ]
        # Should contain the streamed lines (plus some status messages)
        assert 'line1' in stdout_lines
        assert 'line2' in stdout_lines
        assert 'line3' in stdout_lines

    def test_done_event_emitted(self, app, mock_box_manager):
        """_execute_run pushes a 'done' event to the queue."""
        import script_runner

        channel = _make_mock_channel(exit_code=0)
        client = _make_mock_ssh_client(container_id='ctrDone', channel=channel)

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            rec = script_runner.RunRecord('done2', 'test-box', 's.py')
            script_runner._execute_run(rec, 'code')

        # Drain the queue
        messages = []
        while not rec.queue.empty():
            messages.append(rec.queue.get_nowait())

        done_msgs = [m for m in messages if m.get('type') == 'done']
        assert len(done_msgs) >= 1


# ===========================================================================
# _execute_suite
# ===========================================================================

class TestExecuteSuite:

    def test_all_pass(self, app, mock_box_manager):
        """_execute_suite marks suite as completed when all scripts pass."""
        import script_runner
        import script_store

        script_store.add_script('a.py', b'print("a")')
        script_store.add_script('b.py', b'print("b")')

        suite = script_runner.SuiteRecord('suite1', 'test-box', ['a.py', 'b.py'])
        with script_runner._suites_lock:
            script_runner._suites['suite1'] = suite

        channel = _make_mock_channel(exit_code=0)
        client = _make_mock_ssh_client(container_id='ctr1', channel=channel)

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            script_runner._execute_suite(suite)

        assert suite.status == 'completed'
        assert suite.stopped_at is not None
        assert len(suite.results) == 2
        assert all(r['status'] == 'completed' for r in suite.results)

    def test_one_fails(self, app, mock_box_manager):
        """_execute_suite marks suite as failed when any script fails."""
        import script_runner
        import script_store

        script_store.add_script('good.py', b'print("ok")')
        script_store.add_script('bad.py', b'raise Exception()')

        suite = script_runner.SuiteRecord('suite2', 'test-box', ['good.py', 'bad.py'])
        with script_runner._suites_lock:
            script_runner._suites['suite2'] = suite

        call_count = [0]

        def _mock_get_ssh(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                # First script succeeds
                ch = _make_mock_channel(exit_code=0)
            else:
                # Second script fails
                ch = _make_mock_channel(exit_code=1)
            return _make_mock_ssh_client(container_id='ctr2', channel=ch)

        with patch.object(mock_box_manager, 'get_ssh_client', side_effect=_mock_get_ssh):
            script_runner._execute_suite(suite)

        assert suite.status == 'failed'
        assert suite.results[0]['status'] == 'completed'
        assert suite.results[1]['status'] == 'failed'

    def test_cancel_between_scripts(self, app, mock_box_manager):
        """_execute_suite stops when cancelled between script executions."""
        import script_runner
        import script_store

        script_store.add_script('first.py', b'print("1")')
        script_store.add_script('second.py', b'print("2")')

        suite = script_runner.SuiteRecord('suite3', 'test-box', ['first.py', 'second.py'])
        with script_runner._suites_lock:
            script_runner._suites['suite3'] = suite

        call_count = [0]

        def _mock_get_ssh(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                ch = _make_mock_channel(exit_code=0)
                client = _make_mock_ssh_client(container_id='ctr3', channel=ch)

                # Wrap exec_command to cancel after first script finishes
                orig_exec = client.exec_command

                def _exec_with_cancel(cmd, timeout=None):
                    result = orig_exec(cmd, timeout=timeout)
                    return result

                client.exec_command = MagicMock(side_effect=_exec_with_cancel)
                return client
            else:
                ch = _make_mock_channel(exit_code=0)
                return _make_mock_ssh_client(container_id='ctr3', channel=ch)

        # Cancel after first script completes by using a patched start_run
        orig_start_run = script_runner.start_run
        run_count = [0]

        def _patched_start_run(box_id, content, script_name='script.py'):
            run_count[0] += 1
            run_id = orig_start_run(box_id, content, script_name)
            if run_count[0] >= 1:
                # Cancel suite after first run starts, giving it time to finish
                def _delayed_cancel():
                    # Wait for first run to finish
                    rec = script_runner.get_run(run_id)
                    for _ in range(50):
                        if rec.status != 'running':
                            break
                        time.sleep(0.05)
                    suite.cancel()
                threading.Thread(target=_delayed_cancel, daemon=True).start()
            return run_id

        with patch.object(mock_box_manager, 'get_ssh_client', side_effect=_mock_get_ssh):
            with patch.object(script_runner, 'start_run', side_effect=_patched_start_run):
                script_runner._execute_suite(suite)

        assert suite.status == 'cancelled'

    def test_missing_content(self, app, mock_box_manager):
        """_execute_suite handles missing script content gracefully."""
        import script_runner

        suite = script_runner.SuiteRecord(
            'suite4', 'test-box', ['nonexistent.py']
        )
        with script_runner._suites_lock:
            script_runner._suites['suite4'] = suite

        script_runner._execute_suite(suite)

        assert suite.status == 'failed'
        assert len(suite.results) == 1
        assert suite.results[0]['status'] == 'failed'
        assert suite.results[0]['exit_code'] == 1
        assert suite.results[0]['run_id'] is None

    def test_events_emitted_via_queue(self, app, mock_box_manager):
        """_execute_suite pushes script_start, script_end, and suite_done events."""
        import script_runner
        import script_store

        script_store.add_script('evt.py', b'print("event")')

        suite = script_runner.SuiteRecord('suite5', 'test-box', ['evt.py'])
        with script_runner._suites_lock:
            script_runner._suites['suite5'] = suite

        channel = _make_mock_channel(exit_code=0)
        client = _make_mock_ssh_client(container_id='ctrEvt', channel=channel)

        with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
            script_runner._execute_suite(suite)

        # Drain queue
        events = []
        while not suite.queue.empty():
            events.append(suite.queue.get_nowait())

        event_types = [e.get('event') for e in events]
        assert 'script_start' in event_types
        assert 'script_end' in event_types
        assert 'suite_done' in event_types


# ===========================================================================
# stream_output
# ===========================================================================

class TestStreamOutput:

    def test_unknown_run_yields_error(self, app):
        """stream_output yields an error SSE for an unknown run_id."""
        import script_runner

        gen = script_runner.stream_output('no-such-id')
        first = next(gen)

        assert first.startswith('data: ')
        assert first.endswith('\n\n')
        payload = json.loads(first[len('data: '):-2])
        assert payload['type'] == 'error'
        assert 'no-such-id' in payload['line']

    def test_sse_format(self, app):
        """stream_output yields SSE-formatted 'data: {...}\\n\\n' lines."""
        import script_runner

        rec = script_runner.RunRecord('sse1', 'box', 's.py')
        with script_runner._runs_lock:
            script_runner._runs['sse1'] = rec

        # Pre-load queue with a message and done
        rec.queue.put({'type': 'stdout', 'line': 'hello'})
        rec.queue.put({'type': 'done', 'line': ''})
        rec.exit_code = 0

        gen = script_runner.stream_output('sse1')
        lines = list(gen)

        # Each line should match SSE format
        for line in lines:
            assert line.endswith('\n\n')
            assert line.startswith('data: ')

    def test_keepalive_on_timeout(self, app):
        """stream_output emits ': keepalive\\n\\n' when queue times out."""
        import script_runner

        rec = script_runner.RunRecord('ka1', 'box', 's.py')
        with script_runner._runs_lock:
            script_runner._runs['ka1'] = rec

        # Schedule done after a short delay to let the timeout fire once
        def _send_done():
            time.sleep(0.5)
            rec.queue.put({'type': 'done', 'line': ''})

        threading.Thread(target=_send_done, daemon=True).start()

        gen = script_runner.stream_output('ka1')

        # Monkey-patch the queue timeout to be very short for test speed
        original_get = rec.queue.get

        def _fast_get(timeout=30):
            return original_get(timeout=0.2)

        rec.queue.get = _fast_get
        rec.exit_code = 0

        lines = list(gen)

        keepalives = [l for l in lines if l.startswith(': keepalive')]
        assert len(keepalives) >= 1

    def test_stops_on_done(self, app):
        """stream_output stops iterating after receiving a 'done' message."""
        import script_runner

        rec = script_runner.RunRecord('stop1', 'box', 's.py')
        with script_runner._runs_lock:
            script_runner._runs['stop1'] = rec

        rec.queue.put({'type': 'stdout', 'line': 'first'})
        rec.queue.put({'type': 'done', 'line': ''})
        rec.queue.put({'type': 'stdout', 'line': 'should-not-appear'})
        rec.exit_code = 0

        gen = script_runner.stream_output('stop1')
        lines = list(gen)

        # Parse all payloads
        payloads = []
        for line in lines:
            if line.startswith('data: '):
                payloads.append(json.loads(line[len('data: '):-2]))

        # 'should-not-appear' must not be in the payloads
        text_lines = [p.get('line', '') for p in payloads]
        assert 'should-not-appear' not in text_lines

    def test_exit_code_emitted_after_done(self, app):
        """stream_output emits an exit_code event after the done message."""
        import script_runner

        rec = script_runner.RunRecord('ec1', 'box', 's.py')
        with script_runner._runs_lock:
            script_runner._runs['ec1'] = rec

        rec.queue.put({'type': 'done', 'line': ''})
        rec.exit_code = 42

        gen = script_runner.stream_output('ec1')
        lines = list(gen)

        payloads = []
        for line in lines:
            if line.startswith('data: '):
                payloads.append(json.loads(line[len('data: '):-2]))

        # Last payload should be exit_code
        exit_msgs = [p for p in payloads if p.get('type') == 'exit_code']
        assert len(exit_msgs) == 1
        assert exit_msgs[0]['exit_code'] == 42


# ===========================================================================
# start_suite_run
# ===========================================================================

class TestStartSuiteRun:

    def test_returns_8char_id(self, app):
        """start_suite_run returns an 8-character suite ID."""
        import script_runner

        with patch.object(script_runner, '_execute_suite'):
            suite_id = script_runner.start_suite_run('test-box', ['a.py'])

        assert isinstance(suite_id, str)
        assert len(suite_id) == 8

    def test_stores_in_suites_dict(self, app):
        """start_suite_run stores the SuiteRecord in _suites."""
        import script_runner

        with patch.object(script_runner, '_execute_suite'):
            suite_id = script_runner.start_suite_run('test-box', ['a.py', 'b.py'])

        suite = script_runner.get_suite(suite_id)
        assert suite is not None
        assert suite.box_id == 'test-box'
        assert suite.script_names == ['a.py', 'b.py']


# ===========================================================================
# stream_suite_output
# ===========================================================================

class TestStreamSuiteOutput:

    def test_unknown_suite_yields_error(self, app):
        """stream_suite_output yields an error SSE for an unknown suite_id."""
        import script_runner

        gen = script_runner.stream_suite_output('no-such-suite')
        first = next(gen)

        assert first.startswith('data: ')
        payload = json.loads(first[len('data: '):-2])
        assert payload['event'] == 'error'

    def test_stops_on_suite_done(self, app):
        """stream_suite_output stops after receiving a 'suite_done' event."""
        import script_runner

        suite = script_runner.SuiteRecord('ss1', 'box', ['a.py'])
        with script_runner._suites_lock:
            script_runner._suites['ss1'] = suite

        suite.queue.put({'event': 'script_start', 'data': {'index': 0, 'name': 'a.py'}})
        suite.queue.put({'event': 'suite_done', 'data': {'status': 'completed', 'results': []}})
        suite.queue.put({'event': 'extra', 'data': {}})

        gen = script_runner.stream_suite_output('ss1')
        lines = list(gen)

        payloads = []
        for line in lines:
            if line.startswith('data: '):
                payloads.append(json.loads(line[len('data: '):-2]))

        events = [p.get('event') for p in payloads]
        assert 'suite_done' in events
        assert 'extra' not in events


# ===========================================================================
# Edge case tests
# ===========================================================================

class TestExecuteRunEdgeCases:

    def test_ssh_timeout(self, app, mock_box_manager):
        """_execute_run handles SSH connection timeout gracefully."""
        import script_runner
        import socket

        with patch.object(
            mock_box_manager, 'get_ssh_client',
            side_effect=socket.timeout('Connection timed out'),
        ):
            rec = script_runner.RunRecord('timeout1', 'test-box', 's.py')
            script_runner._execute_run(rec, 'code')

        assert rec.status == 'failed'
        assert rec.exit_code == 1
        stderr_lines = [ol['line'] for ol in rec.output_lines if ol['type'] == 'stderr']
        assert any('timed out' in line.lower() or 'timeout' in line.lower() for line in stderr_lines)

    def test_nonzero_exit_codes(self, app, mock_box_manager):
        """_execute_run correctly captures various nonzero exit codes."""
        import script_runner

        for code in [2, 127, 255]:
            channel = _make_mock_channel(exit_code=code)
            client = _make_mock_ssh_client(container_id='ctrX', channel=channel)

            with patch.object(mock_box_manager, 'get_ssh_client', return_value=client):
                rec = script_runner.RunRecord(f'ec{code}', 'test-box', 's.py')
                script_runner._execute_run(rec, 'code')

            assert rec.status == 'failed'
            assert rec.exit_code == code


class TestExecuteSuiteEdgeCases:

    def test_unknown_box_in_suite(self, app, mock_box_manager):
        """_execute_suite fails gracefully when box is unknown."""
        import script_runner
        import script_store

        script_store.add_script('s.py', b'print("s")')

        suite = script_runner.SuiteRecord('suiteX', 'no-such-box', ['s.py'])
        with script_runner._suites_lock:
            script_runner._suites['suiteX'] = suite

        script_runner._execute_suite(suite)

        assert suite.status == 'failed'


class TestStreamOutputEdgeCases:

    def test_completed_run_still_streams(self, app):
        """stream_output works for a run that completes immediately."""
        import script_runner

        rec = script_runner.RunRecord('fast1', 'box', 's.py')
        with script_runner._runs_lock:
            script_runner._runs['fast1'] = rec

        rec.queue.put({'type': 'stdout', 'line': 'done'})
        rec.queue.put({'type': 'done', 'line': ''})
        rec.exit_code = 0
        rec.status = 'completed'

        gen = script_runner.stream_output('fast1')
        lines = list(gen)

        assert len(lines) >= 2  # stdout + done + exit_code
