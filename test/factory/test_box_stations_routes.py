# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/routes/box_stations.py.

Covers all box_stations blueprint endpoints: creating stations, viewing station
detail (with script decoding), uploading/deleting/reordering scripts, and
deleting stations.

All box interactions are mocked via BoxDataClient patches at the route module
level, since _get_client() instantiates BoxDataClient inside the handler.
"""

import base64
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest


def _mock_box_data_client(**method_returns):
    """Build a mock BoxDataClient class and instance with preconfigured returns.

    Usage::

        mock_cls, mock_inst = _mock_box_data_client(
            get_station={'id': 1, 'name': 'S1', 'line_id': 1},
        )
    """
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    for method, return_val in method_returns.items():
        getattr(mock_instance, method).return_value = return_val
    mock_cls.return_value = mock_instance
    return mock_cls, mock_instance


# ---------------------------------------------------------------------------
# POST /box/<box_name>/lines/<line_id>/stations/new
# ---------------------------------------------------------------------------

class TestNewStation:
    """Tests for creating a new station."""

    @patch('routes.box_stations.BoxDataClient')
    def test_create_station(self, mock_bdc_cls, client, mock_box_manager):
        """POST with valid name creates a station and redirects to its detail."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Line 1'},
            create_station={'id': 5, 'name': 'New Station'},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/1/stations/new', data={
            'name': 'New Station',
        })
        assert resp.status_code == 302
        assert '/box/test-box/stations/5' in resp.headers['Location']
        mock_inst.create_station.assert_called_once_with(1, 'New Station')

    @patch('routes.box_stations.BoxDataClient')
    def test_create_station_empty_name(self, mock_bdc_cls, client,
                                       mock_box_manager):
        """POST with empty name shows flash error and re-renders the form."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Line 1'},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/1/stations/new', data={
            'name': '   ',
        })
        assert resp.status_code == 200
        assert b'Station name is required.' in resp.data

    @patch('routes.box_stations.BoxDataClient')
    def test_create_station_unknown_box(self, mock_bdc_cls, client,
                                        mock_box_manager):
        """Unknown box_name redirects to the dashboard."""
        resp = client.post('/box/nonexistent-box/lines/1/stations/new', data={
            'name': 'Test',
        })
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/')


# ---------------------------------------------------------------------------
# GET /box/<box_name>/stations/<station_id>
# ---------------------------------------------------------------------------

class TestStationDetail:
    """Tests for the station detail endpoint."""

    @patch('routes.box_stations.BoxDataClient')
    def test_station_detail_renders(self, mock_bdc_cls, client,
                                    mock_box_manager):
        """GET renders the station detail with scripts and runs."""
        script_content = b'print("hello")'
        content_b64 = base64.b64encode(script_content).decode()

        mock_cls, mock_inst = _mock_box_data_client(
            get_station={'id': 1, 'name': 'Station A', 'line_id': 1},
            get_line={'id': 1, 'name': 'Line 1'},
            list_station_scripts=[
                {'id': 10, 'filename': 'test.py', 'content_b64': content_b64},
            ],
            list_station_runs=[
                {'id': 100, 'status': 'completed', 'started_at': '2025-06-01',
                 'success': 3, 'failure': 0, 'failed_step': '',
                 'duration': 10.5},
            ],
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/stations/1')
        assert resp.status_code == 200

    @patch('routes.box_stations.BoxDataClient')
    def test_station_detail_base64_decode_failure(self, mock_bdc_cls, client,
                                                   mock_box_manager):
        """Bad base64 in content_b64 is handled gracefully (content set to b'')."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_station={'id': 1, 'name': 'Station A', 'line_id': 1},
            get_line={'id': 1, 'name': 'Line 1'},
            list_station_scripts=[
                {'id': 10, 'filename': 'bad.py', 'content_b64': '!!!not-base64!!!'},
            ],
            list_station_runs=[],
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/stations/1')
        assert resp.status_code == 200

    @patch('routes.box_stations.BoxDataClient')
    def test_station_not_found(self, mock_bdc_cls, client, mock_box_manager):
        """When get_station raises, the user is redirected to the lines list."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_inst.get_station.side_effect = RuntimeError('not found')
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/stations/999')
        assert resp.status_code == 302
        assert '/lines' in resp.headers['Location']


# ---------------------------------------------------------------------------
# POST /box/<box_name>/stations/<station_id>/scripts/upload
# ---------------------------------------------------------------------------

class TestUploadScripts:
    """Tests for the script upload endpoint."""

    @patch('routes.box_stations.BoxDataClient')
    def test_upload_py_files(self, mock_bdc_cls, client, mock_box_manager):
        """POST uploads .py files and flashes success."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        data = {
            'files': [(BytesIO(b'print("hi")'), 'test.py')],
        }
        resp = client.post(
            '/box/test-box/stations/1/scripts/upload',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 302
        mock_inst.upload_station_scripts.assert_called_once()

        with client.session_transaction() as sess:
            msgs = dict(sess.get('_flashes', []))
            assert 'Uploaded 1 script(s).' in msgs.get('success', '')

    @patch('routes.box_stations.BoxDataClient')
    def test_upload_non_py_rejected(self, mock_bdc_cls, client,
                                    mock_box_manager):
        """Non-.py files are skipped with a warning flash."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        data = {
            'files': [(BytesIO(b'hello'), 'readme.txt')],
        }
        resp = client.post(
            '/box/test-box/stations/1/scripts/upload',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 302
        mock_inst.upload_station_scripts.assert_not_called()

        with client.session_transaction() as sess:
            msgs = dict(sess.get('_flashes', []))
            assert 'No valid .py files uploaded.' in msgs.get('warning', '')

    @patch('routes.box_stations.BoxDataClient')
    def test_upload_empty_filename(self, mock_bdc_cls, client,
                                   mock_box_manager):
        """Files with empty filenames are skipped."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        data = {
            'files': [(BytesIO(b'content'), '')],
        }
        resp = client.post(
            '/box/test-box/stations/1/scripts/upload',
            data=data,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 302
        mock_inst.upload_station_scripts.assert_not_called()

        with client.session_transaction() as sess:
            msgs = dict(sess.get('_flashes', []))
            assert 'No valid .py files uploaded.' in msgs.get('warning', '')

    @patch('routes.box_stations.BoxDataClient')
    def test_upload_no_files(self, mock_bdc_cls, client, mock_box_manager):
        """POST without a 'files' key flashes danger and redirects."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post(
            '/box/test-box/stations/1/scripts/upload',
            data={},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            msgs = dict(sess.get('_flashes', []))
            assert 'No files provided.' in msgs.get('danger', '')


# ---------------------------------------------------------------------------
# POST /box/<box_name>/stations/<station_id>/scripts/<script_id>/delete
# ---------------------------------------------------------------------------

class TestDeleteScript:
    """Tests for the script deletion endpoint."""

    @patch('routes.box_stations.BoxDataClient')
    def test_delete_script(self, mock_bdc_cls, client, mock_box_manager):
        """POST removes the script and flashes success."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/stations/1/scripts/10/delete')
        assert resp.status_code == 302
        mock_inst.remove_station_script.assert_called_once_with(10)

        with client.session_transaction() as sess:
            msgs = dict(sess.get('_flashes', []))
            assert 'Script removed.' in msgs.get('success', '')

    @patch('routes.box_stations.BoxDataClient')
    def test_delete_script_failure(self, mock_bdc_cls, client,
                                   mock_box_manager):
        """When remove_station_script raises, a danger flash is shown."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_inst.remove_station_script.side_effect = RuntimeError('db error')
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/stations/1/scripts/10/delete')
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            msgs = dict(sess.get('_flashes', []))
            assert 'Failed to remove script' in msgs.get('danger', '')


# ---------------------------------------------------------------------------
# POST /box/<box_name>/stations/<station_id>/scripts/reorder
# ---------------------------------------------------------------------------

class TestReorderScripts:
    """Tests for the script reorder endpoint (JSON API)."""

    @patch('routes.box_stations.BoxDataClient')
    def test_reorder_success(self, mock_bdc_cls, client, mock_box_manager):
        """POST with valid script_ids returns JSON ok."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post(
            '/box/test-box/stations/1/scripts/reorder',
            json={'script_ids': [3, 1, 2]},
        )
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'
        mock_inst.reorder_station_scripts.assert_called_once_with(1, [3, 1, 2])

    @patch('routes.box_stations.BoxDataClient')
    def test_reorder_missing_script_ids(self, mock_bdc_cls, client,
                                        mock_box_manager):
        """POST without script_ids returns 400."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post(
            '/box/test-box/stations/1/scripts/reorder',
            json={'wrong_key': [1, 2]},
        )
        assert resp.status_code == 400
        assert 'script_ids required' in resp.get_json()['error']

    @patch('routes.box_stations.BoxDataClient')
    def test_reorder_invalid_json(self, mock_bdc_cls, client,
                                  mock_box_manager):
        """POST with no JSON body returns 400."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post(
            '/box/test-box/stations/1/scripts/reorder',
            data=b'not json',
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /box/<box_name>/stations/<station_id>/delete
# ---------------------------------------------------------------------------

class TestDeleteStation:
    """Tests for deleting a station."""

    @patch('routes.box_stations.BoxDataClient')
    def test_delete_station_success(self, mock_bdc_cls, client,
                                    mock_box_manager):
        """POST deletes the station and redirects to the line detail page."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_station={'id': 1, 'name': 'Station A', 'line_id': 5},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/stations/1/delete')
        assert resp.status_code == 302
        assert '/box/test-box/lines/5' in resp.headers['Location']
        mock_inst.delete_station.assert_called_once_with(1)

    @patch('routes.box_stations.BoxDataClient')
    def test_delete_station_no_line_id(self, mock_bdc_cls, client,
                                       mock_box_manager):
        """When station lookup fails, redirects to the lines list."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_inst.get_station.side_effect = RuntimeError('not found')
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/stations/1/delete')
        assert resp.status_code == 302
        assert '/lines' in resp.headers['Location']
