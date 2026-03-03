# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/routes/api.py.

Covers all API blueprint endpoints: single runs, streaming, run detail,
cancel, script management, suite execution, and station run start/stop.

Uses Flask test client with mocked external dependencies (script_runner,
box_manager, script_store, step_runner, BoxDataClient) to avoid SSH
connections and real hardware interactions.

NOTE: api.py uses ``from script_runner import start_run, get_run, ...``
which binds names into the ``routes.api`` module namespace. Therefore
mocks must target ``routes.api.<name>`` rather than ``script_runner.<name>``.
"""

import json
from io import BytesIO
from unittest import mock

import pytest

from script_runner import RunRecord, SuiteRecord

# Shorthand patch targets -- the api module re-imports these names.
_API = 'routes.api'


# ---------------------------------------------------------------------------
# 1. POST /api/run
# ---------------------------------------------------------------------------

class TestApiRun:
    def test_no_json_returns_400(self, client, mock_box_manager):
        # Sending JSON null triggers the handler's ``if not data`` check.
        resp = client.post('/api/run', data=b'null',
                           content_type='application/json')
        assert resp.status_code == 400
        assert 'JSON body required' in resp.get_json()['error']

    def test_missing_box_id_returns_400(self, client, mock_box_manager):
        resp = client.post('/api/run', json={
            'script': 'print("hi")',
        })
        assert resp.status_code == 400
        assert 'box_id required' in resp.get_json()['error']

    def test_empty_script_returns_400(self, client, mock_box_manager):
        resp = client.post('/api/run', json={
            'box_id': 'test-box',
            'script': '   ',
        })
        assert resp.status_code == 400
        assert 'script cannot be empty' in resp.get_json()['error']

    def test_unknown_box_returns_404(self, client, mock_box_manager):
        resp = client.post('/api/run', json={
            'box_id': 'nonexistent-box',
            'script': 'print("hi")',
        })
        assert resp.status_code == 404
        assert 'Unknown box' in resp.get_json()['error']

    def test_success_returns_run_id(self, client, mock_box_manager):
        with mock.patch(f'{_API}.start_run', return_value='abc123') as m:
            resp = client.post('/api/run', json={
                'box_id': 'test-box',
                'script': 'print("hello")',
                'script_name': 'hello.py',
            })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == 'abc123'
        m.assert_called_once_with('test-box', 'print("hello")', 'hello.py')


# ---------------------------------------------------------------------------
# 2. GET /api/stream/<run_id>
# ---------------------------------------------------------------------------

class TestApiStream:
    def test_success_returns_sse_response(self, client, mock_box_manager):
        record = RunRecord('stream-1', 'test-box', 'test.py')
        with mock.patch(f'{_API}.get_run', return_value=record):
            with mock.patch(f'{_API}.stream_output',
                            return_value=iter(['data: {"type":"done"}\n\n'])):
                resp = client.get('/api/stream/stream-1')
        assert resp.status_code == 200
        assert resp.content_type.startswith('text/event-stream')

    def test_unknown_run_returns_404(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_run', return_value=None):
            resp = client.get('/api/stream/nonexistent')
        assert resp.status_code == 404
        assert 'Unknown run' in resp.get_json()['error']


# ---------------------------------------------------------------------------
# 3. GET /api/run/<id> (run detail)
# ---------------------------------------------------------------------------

class TestApiRunDetail:
    def test_active_run_record(self, client, mock_box_manager):
        record = RunRecord('detail-1', 'test-box', 'test.py')
        record.output_lines.append({'type': 'stdout', 'line': 'hello'})
        with mock.patch(f'{_API}.get_run', return_value=record):
            resp = client.get('/api/run/detail-1')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == 'detail-1'
        assert data['status'] == 'running'
        assert 'output' in data
        assert len(data['output']) == 1
        assert data['output'][0]['line'] == 'hello'

    def test_active_dict_has_setdefault_output(self, client, mock_box_manager):
        # When get_run returns a dict (completed run still in memory)
        record_dict = {
            'run_id': 'dict-1',
            'box_id': 'test-box',
            'status': 'completed',
        }
        with mock.patch(f'{_API}.get_run', return_value=record_dict):
            resp = client.get('/api/run/dict-1')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == 'dict-1'
        # setdefault should add output key with empty list
        assert data['output'] == []

    def test_unknown_returns_404(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_run', return_value=None):
            resp = client.get('/api/run/nonexistent')
        assert resp.status_code == 404
        assert 'Unknown run' in resp.get_json()['error']


# ---------------------------------------------------------------------------
# 4. POST /api/run/<id>/cancel
# ---------------------------------------------------------------------------

class TestApiCancel:
    def test_running_record_returns_cancelling(self, client, mock_box_manager):
        record = RunRecord('cancel-1', 'test-box', 'test.py')
        record.status = 'running'
        with mock.patch(f'{_API}.get_run', return_value=record):
            resp = client.post('/api/run/cancel-1/cancel')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'cancelling'
        assert record.cancelled

    def test_dict_not_active_returns_400(self, client, mock_box_manager):
        # Dicts represent completed/historical runs -- not cancellable
        record_dict = {'run_id': 'cancel-2', 'status': 'completed'}
        with mock.patch(f'{_API}.get_run', return_value=record_dict):
            resp = client.post('/api/run/cancel-2/cancel')
        assert resp.status_code == 400
        assert 'not active' in resp.get_json()['error']

    def test_non_running_record_returns_400(self, client, mock_box_manager):
        record = RunRecord('cancel-3', 'test-box', 'test.py')
        record.status = 'completed'
        with mock.patch(f'{_API}.get_run', return_value=record):
            resp = client.post('/api/run/cancel-3/cancel')
        assert resp.status_code == 400
        assert 'not active' in resp.get_json()['error']

    def test_unknown_run_returns_404(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_run', return_value=None):
            resp = client.post('/api/run/nonexistent/cancel')
        assert resp.status_code == 404
        assert 'Unknown run' in resp.get_json()['error']


# ---------------------------------------------------------------------------
# 5. Script management endpoints
# ---------------------------------------------------------------------------

class TestScriptManagement:
    def test_list_scripts(self, client, mock_box_manager):
        with mock.patch(f'{_API}.script_store') as mock_ss:
            mock_ss.list_scripts.return_value = [
                {'name': 'a.py', 'size_bytes': 100},
            ]
            resp = client.get('/api/scripts')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['name'] == 'a.py'

    def test_upload_with_files(self, client, mock_box_manager):
        data = {
            'files': (BytesIO(b'print("hi")'), 'test_upload.py'),
        }
        with mock.patch(f'{_API}.script_store') as mock_ss:
            resp = client.post('/api/scripts/upload', data=data,
                               content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        assert 'test_upload.py' in result['added']
        mock_ss.add_script.assert_called_once()

    def test_upload_no_files_returns_400(self, client, mock_box_manager):
        resp = client.post('/api/scripts/upload', data={},
                           content_type='multipart/form-data')
        assert resp.status_code == 400
        assert 'No files provided' in resp.get_json()['error']

    def test_delete_script(self, client, mock_box_manager):
        with mock.patch(f'{_API}.script_store') as mock_ss:
            resp = client.delete('/api/scripts/my_script.py')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'
        mock_ss.remove_script.assert_called_once_with('my_script.py')

    def test_reorder_success(self, client, mock_box_manager):
        with mock.patch(f'{_API}.script_store') as mock_ss:
            resp = client.post('/api/scripts/reorder',
                               json={'order': ['b.py', 'a.py']})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'
        mock_ss.reorder_scripts.assert_called_once_with(['b.py', 'a.py'])

    def test_reorder_bad_data_returns_400(self, client, mock_box_manager):
        resp = client.post('/api/scripts/reorder', json={'wrong_key': []})
        assert resp.status_code == 400
        assert 'order' in resp.get_json()['error']


# ---------------------------------------------------------------------------
# 6. Suite endpoints
# ---------------------------------------------------------------------------

class TestSuiteEndpoints:
    def test_start_suite_success(self, client, mock_box_manager):
        with mock.patch(f'{_API}.script_store') as mock_ss:
            mock_ss.list_scripts.return_value = [
                {'name': 'a.py', 'size_bytes': 50},
            ]
            with mock.patch(f'{_API}.start_suite_run',
                            return_value='suite-abc'):
                resp = client.post('/api/run-suite', json={
                    'box_id': 'test-box',
                })
        assert resp.status_code == 200
        assert resp.get_json()['suite_id'] == 'suite-abc'

    def test_start_suite_no_json(self, client, mock_box_manager):
        resp = client.post('/api/run-suite', data=b'null',
                           content_type='application/json')
        assert resp.status_code == 400
        assert 'JSON body required' in resp.get_json()['error']

    def test_start_suite_no_box_id(self, client, mock_box_manager):
        resp = client.post('/api/run-suite', json={'other': 'data'})
        assert resp.status_code == 400
        assert 'box_id required' in resp.get_json()['error']

    def test_start_suite_no_scripts(self, client, mock_box_manager):
        with mock.patch(f'{_API}.script_store') as mock_ss:
            mock_ss.list_scripts.return_value = []
            resp = client.post('/api/run-suite', json={
                'box_id': 'test-box',
            })
        assert resp.status_code == 400
        assert 'No scripts uploaded' in resp.get_json()['error']

    def test_cancel_running_suite(self, client, mock_box_manager):
        suite = SuiteRecord('suite-cancel', 'test-box', ['a.py'])
        suite.status = 'running'
        with mock.patch(f'{_API}.get_suite', return_value=suite):
            resp = client.post('/api/suite/suite-cancel/cancel')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'cancelling'
        assert suite.cancelled

    def test_list_suites(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_all_suites', return_value=[]):
            resp = client.get('/api/suites')
        assert resp.status_code == 200
        assert resp.get_json() == []


# ---------------------------------------------------------------------------
# 7. Station run start/stop (uses BoxDataClient)
# ---------------------------------------------------------------------------

class TestStationRunStartStop:
    def test_start_success(self, client, mock_box_manager):
        """Start a station run with mocked BoxDataClient."""
        import base64
        script_content = (
            b'from factory import Step\n'
            b'class FlashFW(Step):\n'
            b'    DisplayName = "Flash Firmware"\n'
            b'STEPS = [FlashFW]\n'
        )

        with mock.patch(f'{_API}.BoxDataClient') as mock_bdc_cls:
            mock_bdc = mock_bdc_cls.return_value
            mock_bdc.get_station.return_value = {
                'id': 1, 'name': 'Test Station', 'line_id': 1,
            }
            mock_bdc.list_station_scripts.return_value = [{
                'id': 1,
                'filename': 'test_step.py',
                'content_b64': base64.b64encode(script_content).decode(),
            }]
            mock_bdc.create_station_run.return_value = {'id': 42}

            with mock.patch('step_runner.start_session') as mock_start:
                resp = client.post('/api/station-run/start', json={
                    'station_id': 1,
                    'box_id': 'test-box',
                })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == 42
        assert 'steps' in data
        assert len(data['steps']) == 1
        assert data['steps'][0]['name'] == 'Flash Firmware'
        mock_start.assert_called_once()

    def test_start_no_json_returns_400(self, client, mock_box_manager):
        resp = client.post('/api/station-run/start', data=b'null',
                           content_type='application/json')
        assert resp.status_code == 400
        assert 'JSON body required' in resp.get_json()['error']

    def test_start_missing_station_id_returns_400(self, client,
                                                    mock_box_manager):
        resp = client.post('/api/station-run/start',
                           json={'box_id': 'test-box'})
        assert resp.status_code == 400
        assert 'station_id required' in resp.get_json()['error']

    def test_start_missing_box_id_returns_400(self, client,
                                               mock_box_manager):
        resp = client.post('/api/station-run/start',
                           json={'station_id': 1})
        assert resp.status_code == 400
        assert 'box_id required' in resp.get_json()['error']

    def test_start_no_scripts_returns_400(self, client, mock_box_manager):
        """Station exists but has no scripts."""
        with mock.patch(f'{_API}.BoxDataClient') as mock_bdc_cls:
            mock_bdc = mock_bdc_cls.return_value
            mock_bdc.get_station.return_value = {
                'id': 1, 'name': 'Empty Station',
            }
            mock_bdc.list_station_scripts.return_value = []

            resp = client.post('/api/station-run/start', json={
                'station_id': 1,
                'box_id': 'test-box',
            })
        assert resp.status_code == 400
        assert 'No scripts in station' in resp.get_json()['error']

    def test_start_station_not_found(self, client, mock_box_manager):
        with mock.patch(f'{_API}.BoxDataClient') as mock_bdc_cls:
            mock_bdc = mock_bdc_cls.return_value
            mock_bdc.get_station.return_value = None

            resp = client.post('/api/station-run/start', json={
                'station_id': 99999,
                'box_id': 'test-box',
            })
        assert resp.status_code == 404
        assert 'Station not found' in resp.get_json()['error']

    def test_start_unknown_box_returns_404(self, client, mock_box_manager):
        resp = client.post('/api/station-run/start', json={
            'station_id': 1,
            'box_id': 'nonexistent-box',
        })
        assert resp.status_code == 404
        assert 'Unknown box' in resp.get_json()['error']

    def test_stop_saves_data(self, client, mock_box_manager):
        """Stop endpoint persists to box via BoxDataClient."""
        with mock.patch(f'{_API}.BoxDataClient') as mock_bdc_cls:
            mock_bdc = mock_bdc_cls.return_value
            with mock.patch('step_runner.cleanup_session') as mock_cleanup:
                resp = client.post('/api/station-run/42/stop', json={
                    'box_id': 'test-box',
                    'status': 'completed',
                    'event_log': [{'type': 'step_done', 'result': 'pass'}],
                    'stdout': 'All passed',
                    'stderr': '',
                    'success': 3,
                    'failure': 0,
                    'failed_step': '',
                    'stopped_at': '2025-06-01 12:00:00',
                    'duration': 45.2,
                })
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'
        mock_cleanup.assert_called_once_with(42)
        mock_bdc.update_station_run.assert_called_once()

    def test_stop_without_box_id_still_succeeds(self, client, mock_box_manager):
        """Stop without box_id skips box persistence but still cleans up."""
        with mock.patch('step_runner.cleanup_session') as mock_cleanup:
            resp = client.post('/api/station-run/42/stop', json={})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'
        mock_cleanup.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

class TestApiRunsListEndpoint:
    def test_list_all_runs(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_all_runs',
                        return_value=[
                            {'run_id': 'r1', 'status': 'completed'},
                            {'run_id': 'r2', 'status': 'running'},
                        ]):
            resp = client.get('/api/runs')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2


class TestSuiteStreamEndpoint:
    def test_stream_suite_success(self, client, mock_box_manager):
        suite = SuiteRecord('suite-stream', 'test-box', ['a.py'])
        with mock.patch(f'{_API}.get_suite', return_value=suite):
            with mock.patch(f'{_API}.stream_suite_output',
                            return_value=iter([
                                'data: {"event":"suite_done"}\n\n'
                            ])):
                resp = client.get('/api/stream-suite/suite-stream')
        assert resp.status_code == 200
        assert resp.content_type.startswith('text/event-stream')

    def test_stream_suite_unknown_returns_404(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_suite', return_value=None):
            resp = client.get('/api/stream-suite/nonexistent')
        assert resp.status_code == 404
        assert 'Unknown suite' in resp.get_json()['error']


class TestSuiteCancelEdgeCases:
    def test_cancel_suite_unknown_returns_404(self, client, mock_box_manager):
        with mock.patch(f'{_API}.get_suite', return_value=None):
            resp = client.post('/api/suite/nonexistent/cancel')
        assert resp.status_code == 404
        assert 'Unknown suite' in resp.get_json()['error']

    def test_cancel_suite_dict_returns_400(self, client, mock_box_manager):
        # A dict means the suite is historical, not active
        suite_dict = {'suite_id': 'old', 'status': 'completed'}
        with mock.patch(f'{_API}.get_suite', return_value=suite_dict):
            resp = client.post('/api/suite/old/cancel')
        assert resp.status_code == 400
        assert 'not active' in resp.get_json()['error']

    def test_cancel_non_running_suite_returns_400(self, client,
                                                    mock_box_manager):
        suite = SuiteRecord('suite-done', 'test-box', ['a.py'])
        suite.status = 'completed'
        with mock.patch(f'{_API}.get_suite', return_value=suite):
            resp = client.post('/api/suite/suite-done/cancel')
        assert resp.status_code == 400
        assert 'not active' in resp.get_json()['error']


class TestScriptReorderValueError:
    def test_reorder_raises_value_error_returns_400(self, client,
                                                      mock_box_manager):
        with mock.patch(f'{_API}.script_store') as mock_ss:
            mock_ss.reorder_scripts.side_effect = ValueError(
                'Unknown script: z.py'
            )
            resp = client.post('/api/scripts/reorder',
                               json={'order': ['z.py']})
        assert resp.status_code == 400
        assert 'Unknown script' in resp.get_json()['error']


class TestScriptUploadErrors:
    def test_upload_value_error_reported(self, client, mock_box_manager):
        """When add_script raises ValueError, the error is returned."""
        data = {
            'files': (BytesIO(b'not python'), 'readme.txt'),
        }
        with mock.patch(f'{_API}.script_store') as mock_ss:
            mock_ss.add_script.side_effect = ValueError(
                'Only .py files are allowed'
            )
            resp = client.post('/api/scripts/upload', data=data,
                               content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        assert len(result['errors']) == 1
        assert 'Only .py' in result['errors'][0]['error']


class TestStartSuiteUnknownBox:
    def test_start_suite_unknown_box_returns_404(self, client,
                                                   mock_box_manager):
        resp = client.post('/api/run-suite', json={
            'box_id': 'nonexistent-box',
        })
        assert resp.status_code == 404
        assert 'Unknown box' in resp.get_json()['error']


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestApiStreamEdgeCases:

    def test_stream_response_headers(self, client, mock_box_manager):
        """Streaming response has correct headers for SSE."""
        record = RunRecord('hdr-1', 'test-box', 'test.py')
        with mock.patch(f'{_API}.get_run', return_value=record):
            with mock.patch(f'{_API}.stream_output',
                            return_value=iter(['data: {"type":"done"}\n\n'])):
                resp = client.get('/api/stream/hdr-1')
        assert resp.status_code == 200
        assert 'text/event-stream' in resp.content_type


class TestScriptUploadEdgeCases:

    def test_upload_empty_file(self, client, mock_box_manager):
        """Uploading a zero-byte .py file succeeds."""
        data = {
            'files': (BytesIO(b''), 'empty.py'),
        }
        with mock.patch(f'{_API}.script_store') as mock_ss:
            resp = client.post('/api/scripts/upload', data=data,
                               content_type='multipart/form-data')
        assert resp.status_code == 200
        mock_ss.add_script.assert_called_once()

    def test_upload_unicode_filename(self, client, mock_box_manager):
        """Non-ASCII filename is handled via secure_filename."""
        data = {
            'files': (BytesIO(b'print("hi")'), 'tëst.py'),
        }
        with mock.patch(f'{_API}.script_store') as mock_ss:
            resp = client.post('/api/scripts/upload', data=data,
                               content_type='multipart/form-data')
        assert resp.status_code == 200


class TestStationRunEdgeCases:

    def test_station_run_stop_concurrent(self, client, mock_box_manager):
        """Two simultaneous stop requests both succeed."""
        with mock.patch(f'{_API}.BoxDataClient') as mock_bdc_cls:
            mock_bdc = mock_bdc_cls.return_value
            with mock.patch('step_runner.cleanup_session'):
                resp1 = client.post('/api/station-run/42/stop', json={
                    'box_id': 'test-box', 'status': 'completed',
                })
                resp2 = client.post('/api/station-run/42/stop', json={
                    'box_id': 'test-box', 'status': 'completed',
                })
        assert resp1.status_code == 200
        assert resp2.status_code == 200
