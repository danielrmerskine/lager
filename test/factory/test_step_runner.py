# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/step_runner.py.

Covers StepRunSession lifecycle, session management (start/get/cleanup),
line parsing (_process_line), session finishing (_finish_session), and the
SSH-based execution path (_execute_step_run) with mocked infrastructure.
"""

import json
import queue
import threading
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

import step_runner
from step_runner import (
    StepRunSession,
    _FACTORY_PREFIX,
    _process_line,
    _finish_session,
    _execute_step_run,
    _sessions,
    _sessions_lock,
    start_session,
    get_session,
    cleanup_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_sessions():
    """Ensure _sessions is empty before and after every test."""
    with _sessions_lock:
        _sessions.clear()
    yield
    with _sessions_lock:
        _sessions.clear()


def _make_session(run_id=1, station_id=10, box_id='test-box'):
    """Create a bare StepRunSession without starting any threads."""
    return StepRunSession(run_id, station_id, box_id)


# ---------------------------------------------------------------------------
# StepRunSession -- initial state
# ---------------------------------------------------------------------------

class TestStepRunSessionInit:
    def test_initial_status_is_starting(self):
        s = _make_session()
        assert s.status == 'starting'

    def test_initial_lists_are_empty(self):
        s = _make_session()
        assert s.events == []
        assert s.stdout_lines == []
        assert s.stderr_lines == []

    def test_initial_queues_are_empty(self):
        s = _make_session()
        assert s.to_client.empty()
        assert s.from_client.empty()

    def test_initial_cancel_event_not_set(self):
        s = _make_session()
        assert not s._cancel.is_set()

    def test_initial_channel_is_none(self):
        s = _make_session()
        assert s._channel is None

    def test_stores_constructor_args(self):
        s = StepRunSession(42, 99, 'my-box')
        assert s.run_id == 42
        assert s.station_id == 99
        assert s.box_id == 'my-box'


# ---------------------------------------------------------------------------
# StepRunSession.send_to_script
# ---------------------------------------------------------------------------

class TestSendToScript:
    def test_sends_json_plus_newline(self):
        s = _make_session()
        channel = MagicMock()
        channel.closed = False
        s._channel = channel

        s.send_to_script({'action': 'continue', 'value': 42})

        channel.sendall.assert_called_once()
        sent = channel.sendall.call_args[0][0]
        assert isinstance(sent, bytes)
        text = sent.decode('utf-8')
        assert text.endswith('\n')
        parsed = json.loads(text.rstrip('\n'))
        assert parsed == {'action': 'continue', 'value': 42}

    def test_no_channel_is_noop(self):
        s = _make_session()
        assert s._channel is None
        # Should not raise
        s.send_to_script({'action': 'skip'})

    def test_closed_channel_is_noop(self):
        s = _make_session()
        channel = MagicMock()
        channel.closed = True
        s._channel = channel

        s.send_to_script({'action': 'skip'})
        channel.sendall.assert_not_called()


# ---------------------------------------------------------------------------
# StepRunSession.cancel
# ---------------------------------------------------------------------------

class TestCancel:
    def test_cancel_sets_event(self):
        s = _make_session()
        s.cancel()
        assert s._cancel.is_set()

    def test_cancel_closes_open_channel(self):
        s = _make_session()
        channel = MagicMock()
        channel.closed = False
        s._channel = channel

        s.cancel()
        assert s._cancel.is_set()
        channel.close.assert_called_once()

    def test_cancel_with_no_channel(self):
        s = _make_session()
        # Should not raise when _channel is None
        s.cancel()
        assert s._cancel.is_set()

    def test_cancel_with_already_closed_channel(self):
        s = _make_session()
        channel = MagicMock()
        channel.closed = True
        s._channel = channel

        s.cancel()
        assert s._cancel.is_set()
        channel.close.assert_not_called()


# ---------------------------------------------------------------------------
# Session management: start / get / cleanup
# ---------------------------------------------------------------------------

class TestStartSession:
    @patch('step_runner._execute_step_run')
    def test_creates_and_stores_session(self, mock_exec):
        session = start_session(1, 10, 'test-box', scripts=[])
        assert isinstance(session, StepRunSession)
        assert session.run_id == 1
        assert session.station_id == 10
        assert session.box_id == 'test-box'

        retrieved = get_session(1)
        assert retrieved is session

    @patch('step_runner._execute_step_run')
    def test_attaches_scripts(self, mock_exec):
        scripts = [{'filename': 'a.py', 'content': 'print("a")'}]
        session = start_session(1, 10, 'test-box', scripts=scripts)
        assert session._scripts is scripts

    @patch('step_runner._execute_step_run')
    def test_spawns_daemon_thread(self, mock_exec):
        """start_session launches a background thread targeting _execute_step_run."""
        session = start_session(1, 10, 'test-box', scripts=[])
        # Give the thread a moment to invoke the mock
        mock_exec.assert_called_once_with(session)


class TestGetSession:
    def test_get_existing_session(self):
        s = _make_session(run_id=5)
        with _sessions_lock:
            _sessions[5] = s
        assert get_session(5) is s

    def test_get_nonexistent_returns_none(self):
        assert get_session(999) is None


class TestCleanupSession:
    def test_cleanup_removes_session(self):
        s = _make_session(run_id=7)
        with _sessions_lock:
            _sessions[7] = s
        cleanup_session(7)
        assert get_session(7) is None

    def test_cleanup_nonexistent_is_noop(self):
        # Should not raise
        cleanup_session(99999)


# ---------------------------------------------------------------------------
# _process_line
# ---------------------------------------------------------------------------

class TestProcessLine:
    def test_factory_event_parsed_and_queued(self):
        s = _make_session()
        event_data = {'type': 'lager-factory-step', 'step': 'flash', 'result': True}
        line = _FACTORY_PREFIX + json.dumps(event_data)

        _process_line(s, line)

        assert len(s.events) == 1
        assert s.events[0] == event_data
        queued = s.to_client.get_nowait()
        assert queued == event_data
        # Should NOT be in stdout_lines
        assert s.stdout_lines == []

    def test_malformed_json_treated_as_stdout(self):
        s = _make_session()
        line = _FACTORY_PREFIX + '{not valid json!!!'

        _process_line(s, line)

        assert s.events == []
        assert len(s.stdout_lines) == 1
        assert s.stdout_lines[0] == line
        queued = s.to_client.get_nowait()
        assert queued['type'] == 'lager-log'
        assert queued['file'] == 'stdout'
        assert queued['content'] == line

    def test_regular_line_treated_as_stdout(self):
        s = _make_session()
        line = 'Hello from the script'

        _process_line(s, line)

        assert len(s.stdout_lines) == 1
        assert s.stdout_lines[0] == line
        assert s.events == []
        queued = s.to_client.get_nowait()
        assert queued == {
            'type': 'lager-log', 'file': 'stdout', 'content': line,
        }

    def test_empty_line(self):
        s = _make_session()
        _process_line(s, '')

        assert s.stdout_lines == ['']
        assert s.events == []
        queued = s.to_client.get_nowait()
        assert queued['type'] == 'lager-log'
        assert queued['content'] == ''

    def test_multiple_events_accumulated(self):
        s = _make_session()
        for i in range(3):
            event = {'type': 'step', 'index': i}
            _process_line(s, _FACTORY_PREFIX + json.dumps(event))

        assert len(s.events) == 3
        assert s.to_client.qsize() == 3


# ---------------------------------------------------------------------------
# _finish_session
# ---------------------------------------------------------------------------

class TestFinishSession:
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_sets_status(self, mock_get_mgr, mock_bdc_cls):
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        s = _make_session()
        _finish_session(s, 'completed')
        assert s.status == 'completed'

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_auto_generates_complete_event_when_missing(self, mock_get_mgr,
                                                         mock_bdc_cls):
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        s = _make_session()
        _finish_session(s, 'failed')

        assert len(s.events) == 1
        evt = s.events[0]
        assert evt['type'] == 'lager-factory-complete'
        assert evt['result'] is False  # status != 'completed'
        assert evt['success'] == 0
        assert evt['failure'] == 0
        assert evt['failed_step'] == ''

        queued = s.to_client.get_nowait()
        assert queued['type'] == 'lager-factory-complete'

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_complete_event_result_true_on_completed(self, mock_get_mgr,
                                                      mock_bdc_cls):
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        s = _make_session()
        _finish_session(s, 'completed')

        evt = s.events[0]
        assert evt['result'] is True

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_no_duplicate_complete_if_already_present(self, mock_get_mgr,
                                                       mock_bdc_cls):
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        s = _make_session()
        existing = {
            'type': 'lager-factory-complete',
            'result': True,
            'success': 5,
            'failure': 1,
            'failed_step': 'verify_led',
        }
        s.events.append(existing)

        _finish_session(s, 'completed')

        # Should still be only 1 complete event
        complete_events = [
            e for e in s.events if e.get('type') == 'lager-factory-complete'
        ]
        assert len(complete_events) == 1
        assert complete_events[0] is existing

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_persists_to_box_api(self, mock_get_mgr, mock_bdc_cls):
        """_finish_session calls BoxDataClient.update_station_run()."""
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        mock_bdc = mock_bdc_cls.return_value

        s = _make_session(run_id=42)
        s.stdout_lines.append('line1')
        s.stderr_lines.append('err1')

        existing = {
            'type': 'lager-factory-complete',
            'result': True,
            'success': 3,
            'failure': 2,
            'failed_step': 'step_x',
        }
        s.events.append(existing)

        _finish_session(s, 'completed')

        mock_bdc.update_station_run.assert_called_once()
        call_args = mock_bdc.update_station_run.call_args
        assert call_args[0][0] == 42  # run_id
        kw = call_args[1]
        assert kw['status'] == 'completed'
        assert kw['stdout'] == 'line1'
        assert kw['stderr'] == 'err1'
        assert kw['success'] == 3
        assert kw['failure'] == 2
        assert kw['failed_step'] == 'step_x'
        assert 'stopped_at' in kw

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_box_api_exception_swallowed(self, mock_get_mgr, mock_bdc_cls):
        """If BoxDataClient raises, status is still set."""
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        mock_bdc_cls.return_value.update_station_run.side_effect = RuntimeError(
            'Connection refused'
        )
        s = _make_session()

        # Should not raise
        _finish_session(s, 'failed')

        # Status should still be set
        assert s.status == 'failed'


# ---------------------------------------------------------------------------
# _execute_step_run (mocked SSH)
# ---------------------------------------------------------------------------

class TestExecuteStepRun:
    def _make_mock_manager(self, box=None, ssh_client=None):
        """Build a mock BoxManager returned by get_box_manager()."""
        manager = MagicMock()
        manager.get_box.return_value = box
        manager.get_ssh_client.return_value = ssh_client
        return manager

    def _make_mock_ssh_client(self, container_id='abc123', pythonpath='',
                               exit_code=0, stdout_data=b'', stderr_data=b''):
        """Build a mock paramiko SSHClient with plumbing for exec_command.

        The channel mock simulates the read loop inside _execute_step_run.
        """
        client = MagicMock()

        def fake_exec_command(cmd, timeout=None):
            stdin_mock = MagicMock()
            stdout_mock = MagicMock()
            stderr_mock = MagicMock()

            if 'docker ps' in cmd:
                stdout_mock.read.return_value = (container_id + '\n').encode()
            elif 'PYTHONPATH' in cmd:
                stdout_mock.read.return_value = pythonpath.encode()
            else:
                stdout_mock.read.return_value = b''
                stderr_mock.read.return_value = b''

            return stdin_mock, stdout_mock, stderr_mock

        client.exec_command.side_effect = fake_exec_command

        # SFTP mock
        sftp = MagicMock()
        sftp.file.return_value = MagicMock()
        client.open_sftp.return_value = sftp

        # Transport / channel mock for the main execution
        channel = MagicMock()
        channel.closed = False
        # Simulate: first recv_ready() True with data, then exit
        recv_calls = [True, False]
        channel.recv_ready.side_effect = lambda: recv_calls.pop(0) if recv_calls else False
        channel.recv.return_value = stdout_data

        stderr_calls = [True, False] if stderr_data else [False]
        channel.recv_stderr_ready.side_effect = lambda: stderr_calls.pop(0) if stderr_calls else False
        channel.recv_stderr.return_value = stderr_data

        # First call: not ready (enters loop), second call: ready (exits)
        exit_ready_calls = [False, True]
        channel.exit_status_ready.side_effect = lambda: exit_ready_calls.pop(0) if exit_ready_calls else True
        channel.recv_exit_status.return_value = exit_code

        transport = MagicMock()
        transport.open_session.return_value = channel
        client.get_transport.return_value = transport

        return client, channel

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_unknown_box_sends_error_and_fails(self, mock_get_mgr,
                                                mock_bdc_cls):
        manager = self._make_mock_manager(box=None)
        mock_get_mgr.return_value = manager

        s = _make_session(box_id='nonexistent-box')
        s._scripts = [{'filename': 'test.py', 'content': 'print("hi")'}]

        _execute_step_run(s)

        assert s.status == 'failed'
        # Check error message was queued
        msgs = []
        while not s.to_client.empty():
            msgs.append(s.to_client.get_nowait())
        stderr_msgs = [m for m in msgs if m.get('file') == 'stderr']
        assert any('Unknown box' in m['content'] for m in stderr_msgs)

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_no_scripts_sends_error_and_fails(self, mock_get_mgr,
                                               mock_bdc_cls):
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'}
        )
        mock_get_mgr.return_value = manager

        s = _make_session()
        s._scripts = []

        _execute_step_run(s)

        assert s.status == 'failed'
        msgs = []
        while not s.to_client.empty():
            msgs.append(s.to_client.get_nowait())
        stderr_msgs = [m for m in msgs if m.get('file') == 'stderr']
        assert any('No scripts' in m['content'] for m in stderr_msgs)

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_no_scripts_none_sends_error_and_fails(self, mock_get_mgr,
                                                    mock_bdc_cls):
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'}
        )
        mock_get_mgr.return_value = manager

        s = _make_session()
        s._scripts = None

        _execute_step_run(s)

        assert s.status == 'failed'

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_container_not_found(self, mock_get_mgr, mock_bdc_cls, mock_time):
        mock_time.sleep = MagicMock()  # skip sleeps
        client = MagicMock()

        def fake_exec(cmd, timeout=None):
            s_in, s_out, s_err = MagicMock(), MagicMock(), MagicMock()
            if 'docker ps' in cmd:
                s_out.read.return_value = b''  # empty = no container
            else:
                s_out.read.return_value = b''
            return s_in, s_out, s_err

        client.exec_command.side_effect = fake_exec
        sftp = MagicMock()
        sftp.file.return_value = MagicMock()
        client.open_sftp.return_value = sftp

        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session()
        s._scripts = [{'filename': 'test.py', 'content': 'print("hi")'}]

        _execute_step_run(s)

        assert s.status == 'failed'
        msgs = []
        while not s.to_client.empty():
            msgs.append(s.to_client.get_nowait())
        stderr_msgs = [m for m in msgs if m.get('file') == 'stderr']
        assert any('not found' in m['content'] or 'not running' in m['content']
                    for m in stderr_msgs)

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_needs_wrapper_for_steps_without_run(self, mock_get_mgr,
                                                  mock_bdc_cls, mock_time):
        """Script with STEPS list but no factory.run() should trigger wrapper generation."""
        mock_time.sleep = MagicMock()

        script_content = (
            'from factory import Step\n'
            'class Check(Step):\n'
            '    def run(self): pass\n'
            'STEPS = [Check]\n'
        )
        client, channel = self._make_mock_ssh_client(
            exit_code=0, stdout_data=b'done\n'
        )
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=100)
        s._scripts = [{'filename': 'test_steps.py', 'content': script_content}]

        _execute_step_run(s)

        assert s.status == 'completed'

        # Verify wrapper was created: check that a second sftp was opened for wrapper
        # open_sftp should be called twice (once for scripts, once for wrapper)
        assert client.open_sftp.call_count == 2

        # The exec_command for the final run should reference the wrapper filename
        cmd_arg = channel.exec_command.call_args[0][0]
        assert '_lager_wrapper_100' in cmd_arg

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_no_wrapper_when_factory_run_present(self, mock_get_mgr,
                                                  mock_bdc_cls, mock_time):
        """Script with factory.run() should NOT generate a wrapper."""
        mock_time.sleep = MagicMock()

        script_content = (
            'from factory import Step, run\n'
            'class Check(Step):\n'
            '    def run(self): pass\n'
            'STEPS = [Check]\n'
            'factory.run(STEPS)\n'
        )
        client, channel = self._make_mock_ssh_client(
            exit_code=0, stdout_data=b'done\n'
        )
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=200)
        s._scripts = [{'filename': 'test_run.py', 'content': script_content}]

        _execute_step_run(s)

        assert s.status == 'completed'
        # open_sftp called only once (no wrapper upload)
        assert client.open_sftp.call_count == 1

        cmd_arg = channel.exec_command.call_args[0][0]
        assert '_lager_wrapper_' not in cmd_arg
        assert 'test_run.py' in cmd_arg

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_no_wrapper_when_run_steps_present(self, mock_get_mgr,
                                                mock_bdc_cls, mock_time):
        """Script with run(STEPS) should NOT generate a wrapper."""
        mock_time.sleep = MagicMock()

        script_content = (
            'from factory import Step, run\n'
            'class Check(Step):\n'
            '    def run(self): pass\n'
            'STEPS = [Check]\n'
            'run(STEPS)\n'
        )
        client, channel = self._make_mock_ssh_client(
            exit_code=0, stdout_data=b'done\n'
        )
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=300)
        s._scripts = [{'filename': 'test_run2.py', 'content': script_content}]

        _execute_step_run(s)

        # open_sftp called only once
        assert client.open_sftp.call_count == 1

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_user_response_forwarded_from_queue(self, mock_get_mgr,
                                                 mock_bdc_cls, mock_time):
        """Responses placed on from_client queue are sent to the script."""
        mock_time.sleep = MagicMock()

        client, channel = self._make_mock_ssh_client(
            exit_code=0, stdout_data=b'prompt\n'
        )

        # Override recv_ready/exit_status to allow a few iterations so the
        # from_client queue gets drained.
        recv_sequence = [True, False, False]
        channel.recv_ready.side_effect = lambda: recv_sequence.pop(0) if recv_sequence else False
        exit_sequence = [False, False, True]
        channel.exit_status_ready.side_effect = lambda: exit_sequence.pop(0) if exit_sequence else True

        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=400)
        s._scripts = [{'filename': 'interactive.py', 'content': 'print("hi")'}]

        # Pre-load a response into from_client
        response_data = {'action': 'continue', 'value': 'yes'}
        s.from_client.put(response_data)

        _execute_step_run(s)

        # Verify the channel received the serialized response
        expected_bytes = (json.dumps(response_data) + '\n').encode()
        channel.sendall.assert_called_with(expected_bytes)

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_nonzero_exit_code_marks_failed(self, mock_get_mgr, mock_bdc_cls,
                                             mock_time):
        mock_time.sleep = MagicMock()

        client, channel = self._make_mock_ssh_client(
            exit_code=1, stdout_data=b'error output\n'
        )
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=500)
        s._scripts = [{'filename': 'fail.py', 'content': 'import sys; sys.exit(1)'}]

        _execute_step_run(s)

        assert s.status == 'failed'

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_ssh_exception_marks_failed(self, mock_get_mgr, mock_bdc_cls,
                                         mock_time):
        mock_time.sleep = MagicMock()

        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
        )
        manager.get_ssh_client.side_effect = Exception('Connection refused')
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=600)
        s._scripts = [{'filename': 'test.py', 'content': 'print("hi")'}]

        _execute_step_run(s)

        assert s.status == 'failed'
        msgs = []
        while not s.to_client.empty():
            msgs.append(s.to_client.get_nowait())
        stderr_msgs = [m for m in msgs if m.get('file') == 'stderr']
        assert any('Connection refused' in m['content'] for m in stderr_msgs)

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_bytes_content_decoded(self, mock_get_mgr, mock_bdc_cls,
                                    mock_time):
        """Script content as bytes should be handled without error."""
        mock_time.sleep = MagicMock()

        client, channel = self._make_mock_ssh_client(
            exit_code=0, stdout_data=b'ok\n'
        )
        manager = self._make_mock_manager(
            box={'ip': '192.0.2.1', 'container': 'lager'},
            ssh_client=client,
        )
        mock_get_mgr.return_value = manager

        s = _make_session(run_id=700)
        s._scripts = [{'filename': 'test.py', 'content': b'print("bytes")'}]

        _execute_step_run(s)

        assert s.status == 'completed'


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestSendToScriptEdgeCases:

    def test_send_to_script_broken_pipe(self):
        """send_to_script propagates OSError from channel.sendall."""
        s = _make_session()
        channel = MagicMock()
        channel.closed = False
        channel.sendall.side_effect = OSError('Broken pipe')
        s._channel = channel

        with pytest.raises(OSError, match='Broken pipe'):
            s.send_to_script({'action': 'continue'})


class TestProcessLineEdgeCases:

    def test_process_line_null_bytes(self):
        """Line with embedded null bytes treated as stdout."""
        s = _make_session()
        line = 'hello\x00world'

        _process_line(s, line)

        assert len(s.stdout_lines) == 1
        assert s.stdout_lines[0] == line

    def test_process_line_double_prefix(self):
        """Line with prefix appearing twice still parsed correctly."""
        s = _make_session()
        event_data = {'type': 'test-event', 'data': 'value'}
        line = _FACTORY_PREFIX + json.dumps(event_data)

        _process_line(s, line)

        assert len(s.events) == 1
        assert s.events[0] == event_data


class TestFinishSessionEdgeCases:

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_finish_session_called_twice(self, mock_get_mgr, mock_bdc_cls):
        """Calling _finish_session twice is safe (idempotent status set)."""
        mock_get_mgr.return_value.get_box.return_value = {'ip': '192.0.2.1'}
        s = _make_session()

        _finish_session(s, 'completed')
        assert s.status == 'completed'

        _finish_session(s, 'failed')
        assert s.status == 'failed'

    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_finish_session_box_not_found(self, mock_get_mgr, mock_bdc_cls):
        """_finish_session handles box not found gracefully."""
        mock_get_mgr.return_value.get_box.return_value = None
        s = _make_session()

        # Should not raise
        _finish_session(s, 'failed')
        assert s.status == 'failed'


class TestExecuteStepRunEdgeCases(TestExecuteStepRun):

    @patch('step_runner.time')
    @patch('step_runner.BoxDataClient')
    @patch('step_runner.get_box_manager')
    def test_exit_codes_127_and_255(self, mock_get_mgr, mock_bdc_cls, mock_time):
        """Various nonzero exit codes are handled."""
        mock_time.sleep = MagicMock()

        for code in [127, 255]:
            client, channel = self._make_mock_ssh_client(
                exit_code=code, stdout_data=b'err\n'
            )
            manager = self._make_mock_manager(
                box={'ip': '192.0.2.1', 'container': 'lager'},
                ssh_client=client,
            )
            mock_get_mgr.return_value = manager

            s = _make_session(run_id=800 + code)
            s._scripts = [{'filename': 'test.py', 'content': 'print("hi")'}]

            _execute_step_run(s)

            assert s.status == 'failed'
