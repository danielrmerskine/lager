# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/box_data_client.py.

Covers URL construction, JSON body construction, response parsing,
error handling, base64 encoding for script uploads, and query parameter
filtering for all BoxDataClient methods.
"""

import base64
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(json_data=None):
    """Create a mock requests.Response with a configurable .json() return."""
    resp = MagicMock()
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Constructor / URL construction
# ---------------------------------------------------------------------------

class TestConstructor:

    def test_default_port_and_timeout(self):
        """BoxDataClient builds the correct base_url with default port/timeout."""
        from box_data_client import BoxDataClient
        client = BoxDataClient('192.168.1.50')
        assert client.base_url == 'http://192.168.1.50:9000/dashboard'
        assert client.timeout == 10

    def test_custom_port_and_timeout(self):
        """BoxDataClient respects custom port and timeout arguments."""
        from box_data_client import BoxDataClient
        client = BoxDataClient('192.0.2.1', port=8080, timeout=30)
        assert client.base_url == 'http://192.0.2.1:8080/dashboard'
        assert client.timeout == 30


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:

    @patch('box_data_client.requests')
    def test_health_success(self, mock_requests):
        """health() returns parsed JSON on success."""
        from box_data_client import BoxDataClient
        payload = {'available': True, 'version': '1.2.3'}
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.health()

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/health',
            timeout=3,
        )

    @patch('box_data_client.requests')
    def test_health_returns_unavailable_on_exception(self, mock_requests):
        """health() returns {'available': False} when the request fails."""
        from box_data_client import BoxDataClient
        mock_requests.get.side_effect = ConnectionError('refused')

        client = BoxDataClient('192.0.2.1')
        result = client.health()

        assert result == {'available': False}

    @patch('box_data_client.requests')
    def test_is_available_true(self, mock_requests):
        """is_available() returns True when health reports available."""
        from box_data_client import BoxDataClient
        mock_requests.get.return_value = _make_mock_response({'available': True})

        client = BoxDataClient('192.0.2.1')
        assert client.is_available() is True

    @patch('box_data_client.requests')
    def test_is_available_false_on_error(self, mock_requests):
        """is_available() returns False when health() catches an exception."""
        from box_data_client import BoxDataClient
        mock_requests.get.side_effect = Exception('network down')

        client = BoxDataClient('192.0.2.1')
        assert client.is_available() is False


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

class TestLines:

    @patch('box_data_client.requests')
    def test_list_lines(self, mock_requests):
        """list_lines() GETs /lines and returns parsed JSON."""
        from box_data_client import BoxDataClient
        payload = [{'id': 1, 'name': 'Line A'}]
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.list_lines()

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/lines',
            params={},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_create_line(self, mock_requests):
        """create_line() POSTs name, description, and extra kwargs to /lines."""
        from box_data_client import BoxDataClient
        resp_payload = {'id': 7, 'name': 'New Line'}
        mock_requests.post.return_value = _make_mock_response(resp_payload)

        client = BoxDataClient('192.0.2.1')
        result = client.create_line('New Line', description='desc', box_id='box-1')

        assert result == resp_payload
        mock_requests.post.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/lines',
            json={'name': 'New Line', 'description': 'desc', 'box_id': 'box-1'},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_create_line_default_description(self, mock_requests):
        """create_line() sends empty description when none is provided."""
        from box_data_client import BoxDataClient
        mock_requests.post.return_value = _make_mock_response({'id': 1})

        client = BoxDataClient('192.0.2.1')
        client.create_line('Minimal')

        call_kwargs = mock_requests.post.call_args
        sent_json = call_kwargs.kwargs['json'] if 'json' in call_kwargs.kwargs else call_kwargs[1]['json']
        assert sent_json['description'] == ''

    @patch('box_data_client.requests')
    def test_get_line(self, mock_requests):
        """get_line() GETs /lines/<id> and returns parsed JSON."""
        from box_data_client import BoxDataClient
        payload = {'id': 3, 'name': 'Line 3'}
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.get_line(3)

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/lines/3',
            params={},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_update_line(self, mock_requests):
        """update_line() PUTs kwargs to /lines/<id>."""
        from box_data_client import BoxDataClient
        mock_requests.put.return_value = _make_mock_response({'ok': True})

        client = BoxDataClient('192.0.2.1')
        result = client.update_line(5, name='Renamed', description='new desc')

        assert result == {'ok': True}
        mock_requests.put.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/lines/5',
            json={'name': 'Renamed', 'description': 'new desc'},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_delete_line(self, mock_requests):
        """delete_line() DELETEs /lines/<id>."""
        from box_data_client import BoxDataClient
        mock_requests.delete.return_value = _make_mock_response({'deleted': True})

        client = BoxDataClient('192.0.2.1')
        result = client.delete_line(2)

        assert result == {'deleted': True}
        mock_requests.delete.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/lines/2',
            timeout=10,
        )


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------

class TestStations:

    @patch('box_data_client.requests')
    def test_list_stations(self, mock_requests):
        """list_stations() GETs /lines/<line_id>/stations."""
        from box_data_client import BoxDataClient
        payload = [{'id': 1, 'name': 'Station A'}]
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.list_stations(line_id=4)

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/lines/4/stations',
            params={},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_create_station(self, mock_requests):
        """create_station() POSTs line_id and name to /stations."""
        from box_data_client import BoxDataClient
        resp_payload = {'id': 11, 'name': 'New Station'}
        mock_requests.post.return_value = _make_mock_response(resp_payload)

        client = BoxDataClient('192.0.2.1')
        result = client.create_station(line_id=3, name='New Station')

        assert result == resp_payload
        mock_requests.post.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/stations',
            json={'line_id': 3, 'name': 'New Station'},
            timeout=10,
        )


# ---------------------------------------------------------------------------
# Station Scripts
# ---------------------------------------------------------------------------

class TestStationScripts:

    @patch('box_data_client.requests')
    def test_upload_station_scripts_bytes_content(self, mock_requests):
        """upload_station_scripts() base64-encodes bytes content correctly."""
        from box_data_client import BoxDataClient
        mock_requests.post.return_value = _make_mock_response({'uploaded': 2})

        client = BoxDataClient('192.0.2.1')
        files = [
            ('test.py', b'print("hello")'),
            ('setup.py', b'import os'),
        ]
        result = client.upload_station_scripts(station_id=7, file_list=files)

        assert result == {'uploaded': 2}
        call_args = mock_requests.post.call_args
        sent_json = call_args.kwargs.get('json') or call_args[1].get('json')
        scripts = sent_json['scripts']

        assert len(scripts) == 2
        assert scripts[0]['filename'] == 'test.py'
        assert base64.b64decode(scripts[0]['content_b64']) == b'print("hello")'
        assert scripts[1]['filename'] == 'setup.py'
        assert base64.b64decode(scripts[1]['content_b64']) == b'import os'

        # URL is correct
        assert call_args[0][0] == 'http://192.0.2.1:9000/dashboard/stations/7/scripts'

    @patch('box_data_client.requests')
    def test_upload_station_scripts_string_content(self, mock_requests):
        """upload_station_scripts() auto-encodes string content to bytes before b64."""
        from box_data_client import BoxDataClient
        mock_requests.post.return_value = _make_mock_response({'uploaded': 1})

        client = BoxDataClient('192.0.2.1')
        files = [('auto.py', 'print("auto")')]
        client.upload_station_scripts(station_id=1, file_list=files)

        call_args = mock_requests.post.call_args
        sent_json = call_args.kwargs.get('json') or call_args[1].get('json')
        decoded = base64.b64decode(sent_json['scripts'][0]['content_b64'])
        assert decoded == b'print("auto")'


# ---------------------------------------------------------------------------
# Station Runs
# ---------------------------------------------------------------------------

class TestStationRuns:

    @patch('box_data_client.requests')
    def test_list_station_runs_no_filters(self, mock_requests):
        """list_station_runs() sends only limit when no filters are given."""
        from box_data_client import BoxDataClient
        payload = [{'id': 'run-1'}]
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.list_station_runs()

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/runs',
            params={'limit': 100},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_list_station_runs_with_station_filter(self, mock_requests):
        """list_station_runs() includes station_id in params when specified."""
        from box_data_client import BoxDataClient
        mock_requests.get.return_value = _make_mock_response([])

        client = BoxDataClient('192.0.2.1')
        client.list_station_runs(station_id=5, limit=50)

        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/runs',
            params={'limit': 50, 'station_id': 5},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_list_station_runs_with_line_filter(self, mock_requests):
        """list_station_runs() includes line_id in params when specified."""
        from box_data_client import BoxDataClient
        mock_requests.get.return_value = _make_mock_response([])

        client = BoxDataClient('192.0.2.1')
        client.list_station_runs(line_id=2)

        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/runs',
            params={'limit': 100, 'line_id': 2},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_list_station_runs_with_both_filters(self, mock_requests):
        """list_station_runs() includes both station_id and line_id when both given."""
        from box_data_client import BoxDataClient
        mock_requests.get.return_value = _make_mock_response([])

        client = BoxDataClient('192.0.2.1')
        client.list_station_runs(station_id=3, line_id=1, limit=25)

        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/runs',
            params={'limit': 25, 'station_id': 3, 'line_id': 1},
            timeout=10,
        )


# ---------------------------------------------------------------------------
# Webcam
# ---------------------------------------------------------------------------

class TestWebcam:

    @patch('box_data_client.requests')
    def test_list_webcam_streams(self, mock_requests):
        """list_webcam_streams() GETs /webcam/streams."""
        from box_data_client import BoxDataClient
        payload = [{'url': 'http://cam1/stream'}]
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.list_webcam_streams()

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/webcam/streams',
            params={},
            timeout=10,
        )


# ---------------------------------------------------------------------------
# HTTP error propagation
# ---------------------------------------------------------------------------

class TestErrorPropagation:

    @patch('box_data_client.requests')
    def test_raise_for_status_propagates(self, mock_requests):
        """HTTP errors from raise_for_status() propagate to the caller."""
        from box_data_client import BoxDataClient
        from requests.exceptions import HTTPError

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = HTTPError('404 Not Found')
        mock_requests.get.return_value = mock_resp

        client = BoxDataClient('192.0.2.1')
        with pytest.raises(HTTPError):
            client.list_lines()


# ---------------------------------------------------------------------------
# Edge case tests - untested methods and error handling
# ---------------------------------------------------------------------------

class TestGetStation:

    @patch('box_data_client.requests')
    def test_get_station(self, mock_requests):
        """get_station() GETs /stations/<id>."""
        from box_data_client import BoxDataClient
        payload = {'id': 5, 'name': 'Station A', 'line_id': 1}
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.get_station(5)

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/stations/5',
            params={},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_update_station(self, mock_requests):
        """update_station() PUTs kwargs to /stations/<id>."""
        from box_data_client import BoxDataClient
        mock_requests.put.return_value = _make_mock_response({'ok': True})

        client = BoxDataClient('192.0.2.1')
        result = client.update_station(5, name='Renamed')

        assert result == {'ok': True}
        mock_requests.put.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/stations/5',
            json={'name': 'Renamed'},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_delete_station(self, mock_requests):
        """delete_station() DELETEs /stations/<id>."""
        from box_data_client import BoxDataClient
        mock_requests.delete.return_value = _make_mock_response({'deleted': True})

        client = BoxDataClient('192.0.2.1')
        result = client.delete_station(5)

        assert result == {'deleted': True}
        mock_requests.delete.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/stations/5',
            timeout=10,
        )


class TestStationRunMethods:

    @patch('box_data_client.requests')
    def test_create_station_run(self, mock_requests):
        """create_station_run() POSTs station_id to /runs."""
        from box_data_client import BoxDataClient
        mock_requests.post.return_value = _make_mock_response({'id': 42})

        client = BoxDataClient('192.0.2.1')
        result = client.create_station_run(station_id=10)

        assert result == {'id': 42}
        mock_requests.post.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/runs',
            json={'station_id': 10},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_update_station_run(self, mock_requests):
        """update_station_run() PUTs kwargs to /runs/<id>."""
        from box_data_client import BoxDataClient
        mock_requests.put.return_value = _make_mock_response({'ok': True})

        client = BoxDataClient('192.0.2.1')
        result = client.update_station_run(42, status='completed', stdout='hello')

        assert result == {'ok': True}
        mock_requests.put.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/runs/42',
            json={'status': 'completed', 'stdout': 'hello'},
            timeout=10,
        )


class TestStationScriptMethods:

    @patch('box_data_client.requests')
    def test_list_station_scripts(self, mock_requests):
        """list_station_scripts() GETs /stations/<id>/scripts."""
        from box_data_client import BoxDataClient
        payload = [{'id': 1, 'filename': 'test.py'}]
        mock_requests.get.return_value = _make_mock_response(payload)

        client = BoxDataClient('192.0.2.1')
        result = client.list_station_scripts(station_id=7)

        assert result == payload
        mock_requests.get.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/stations/7/scripts',
            params={},
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_remove_station_script(self, mock_requests):
        """remove_station_script() DELETEs /scripts/<id>."""
        from box_data_client import BoxDataClient
        mock_requests.delete.return_value = _make_mock_response({'deleted': True})

        client = BoxDataClient('192.0.2.1')
        result = client.remove_station_script(script_id=15)

        assert result == {'deleted': True}
        mock_requests.delete.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/scripts/15',
            timeout=10,
        )

    @patch('box_data_client.requests')
    def test_reorder_station_scripts(self, mock_requests):
        """reorder_station_scripts() PUTs script_ids to /stations/<id>/scripts/reorder."""
        from box_data_client import BoxDataClient
        mock_requests.put.return_value = _make_mock_response({'ok': True})

        client = BoxDataClient('192.0.2.1')
        result = client.reorder_station_scripts(station_id=7, script_ids=[3, 1, 2])

        assert result == {'ok': True}
        mock_requests.put.assert_called_once_with(
            'http://192.0.2.1:9000/dashboard/stations/7/scripts/reorder',
            json={'script_ids': [3, 1, 2]},
            timeout=10,
        )


class TestConnectionErrors:

    @patch('box_data_client.requests')
    def test_connection_refused(self, mock_requests):
        """ConnectionError from requests propagates to caller."""
        from box_data_client import BoxDataClient
        mock_requests.get.side_effect = ConnectionError('Connection refused')

        client = BoxDataClient('192.0.2.1')
        with pytest.raises(ConnectionError):
            client.list_lines()

    @patch('box_data_client.requests')
    def test_health_timeout(self, mock_requests):
        """health() returns unavailable on timeout."""
        from box_data_client import BoxDataClient
        import requests as real_requests
        mock_requests.get.side_effect = real_requests.Timeout('timed out')

        client = BoxDataClient('192.0.2.1')
        result = client.health()
        assert result == {'available': False}

    @patch('box_data_client.requests')
    def test_create_line_http_500(self, mock_requests):
        """Server error (500) propagates via raise_for_status."""
        from box_data_client import BoxDataClient
        from requests.exceptions import HTTPError

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = HTTPError('500 Server Error')
        mock_requests.post.return_value = mock_resp

        client = BoxDataClient('192.0.2.1')
        with pytest.raises(HTTPError):
            client.create_line('Test')
