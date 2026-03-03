# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/routes/webcam.py.

Covers the webcam viewer page, MJPEG proxy endpoint, start/stop API
endpoints (including input validation and injection rejection), and the
_run_script_on_box helper -- including timeout handling.

All box interactions are mocked; no real hardware is needed.
"""

from unittest.mock import patch, MagicMock

import pytest
import requests


# ---------------------------------------------------------------------------
# GET /box/<box_id>/webcam -- webcam viewer
# ---------------------------------------------------------------------------

class TestWebcamViewer:
    """Tests for the webcam viewer page."""

    @patch('routes.webcam._get_webcam_info', return_value=([], {}))
    def test_webcam_viewer_renders(self, mock_info, client, mock_box_manager):
        """GET /box/test-box/webcam returns 200."""
        resp = client.get('/box/test-box/webcam')
        assert resp.status_code == 200

    @patch('routes.webcam._get_webcam_info', return_value=([], {}))
    def test_webcam_viewer_unknown_box(self, mock_info, client,
                                       mock_box_manager):
        """Unknown box redirects to dashboard."""
        resp = client.get('/box/no-such-box/webcam')
        assert resp.status_code == 302
        assert '/' in resp.headers['Location']

    @patch('routes.webcam._get_webcam_info')
    def test_webcam_viewer_enriches_nets(self, mock_info, client,
                                         mock_box_manager):
        """Stream status is merged into nets (streaming=True when port set)."""
        webcam_nets = [
            {'name': 'cam0', 'role': 'webcam'},
            {'name': 'cam1', 'role': 'webcam'},
        ]
        streams = {
            'cam0': {'port': 8081},
            # cam1 has no active stream
        }
        mock_info.return_value = (webcam_nets, streams)

        resp = client.get('/box/test-box/webcam')
        assert resp.status_code == 200
        # After enrichment, cam0 should be streaming, cam1 should not.
        # We verify indirectly: the page should contain the proxy URL for cam0.
        assert b'cam0' in resp.data


# ---------------------------------------------------------------------------
# GET /box/<box_id>/webcam/<net_name>/stream -- MJPEG proxy
# ---------------------------------------------------------------------------

class TestWebcamProxy:
    """Tests for the MJPEG proxy endpoint."""

    @patch('routes.webcam.requests')
    @patch('routes.webcam._run_script_on_box')
    def test_webcam_proxy_streams(self, mock_run_script, mock_requests,
                                   client, mock_box_manager):
        """Active stream returns chunked response."""
        import json
        mock_run_script.return_value = json.dumps({
            'cam0': {'port': 8081},
        })

        # Mock the streaming GET request
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = iter([b'frame-data'])
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_requests.get.return_value = mock_resp

        resp = client.get('/box/test-box/webcam/cam0/stream')
        assert resp.status_code == 200
        assert 'multipart/x-mixed-replace' in resp.content_type

    @patch('routes.webcam._run_script_on_box')
    def test_webcam_proxy_no_stream(self, mock_run_script, client,
                                     mock_box_manager):
        """Inactive stream returns 404."""
        import json
        mock_run_script.return_value = json.dumps({})

        resp = client.get('/box/test-box/webcam/cam0/stream')
        assert resp.status_code == 404

    @patch('routes.webcam._run_script_on_box')
    def test_webcam_proxy_unknown_box(self, mock_run_script, client,
                                       mock_box_manager):
        """Unknown box returns 404."""
        resp = client.get('/box/no-such-box/webcam/cam0/stream')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/box/<box_id>/webcam/start
# ---------------------------------------------------------------------------

class TestWebcamStart:
    """Tests for the webcam start API endpoint."""

    @patch('routes.webcam._run_script_on_box')
    def test_webcam_start_success(self, mock_run_script, client,
                                   mock_box_manager):
        """POST with valid net_name returns JSON result."""
        import json
        mock_run_script.return_value = json.dumps({
            'ok': True, 'url': 'http://192.0.2.1:8081/stream', 'port': 8081,
        })

        resp = client.post(
            '/api/box/test-box/webcam/start',
            json={'net': 'cam0'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True

    def test_webcam_start_missing_net(self, client, mock_box_manager):
        """Missing 'net' in request body returns 400."""
        resp = client.post(
            '/api/box/test-box/webcam/start',
            json={},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'net required' in data['error']

    def test_webcam_start_rejects_injection(self, client, mock_box_manager):
        """SECURITY: net_name with quotes/semicolons returns 400."""
        payloads = [
            "'; import os; os.system('rm -rf /'); '",
            "cam1; drop table",
        ]
        for payload in payloads:
            resp = client.post(
                '/api/box/test-box/webcam/start',
                json={'net': payload},
            )
            assert resp.status_code == 400, (
                f"Expected 400 for payload {payload!r}, got {resp.status_code}"
            )
            data = resp.get_json()
            assert 'Invalid net name' in data['error']

    def test_webcam_start_rejects_spaces(self, client, mock_box_manager):
        """net_name with spaces returns 400."""
        resp = client.post(
            '/api/box/test-box/webcam/start',
            json={'net': 'net name with spaces'},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'Invalid net name' in data['error']

    def test_webcam_start_unknown_box(self, client, mock_box_manager):
        """Unknown box returns 404."""
        resp = client.post(
            '/api/box/no-such-box/webcam/start',
            json={'net': 'cam0'},
        )
        assert resp.status_code == 404
        data = resp.get_json()
        assert 'Box not found' in data['error']


# ---------------------------------------------------------------------------
# POST /api/box/<box_id>/webcam/stop
# ---------------------------------------------------------------------------

class TestWebcamStop:
    """Tests for the webcam stop API endpoint."""

    @patch('routes.webcam._run_script_on_box')
    def test_webcam_stop_success(self, mock_run_script, client,
                                  mock_box_manager):
        """POST stops stream and returns JSON result."""
        import json
        mock_run_script.return_value = json.dumps({'ok': True})

        resp = client.post(
            '/api/box/test-box/webcam/stop',
            json={'net': 'cam0'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True

    def test_webcam_stop_missing_net(self, client, mock_box_manager):
        """Missing 'net' in request body returns 400."""
        resp = client.post(
            '/api/box/test-box/webcam/stop',
            json={},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'net required' in data['error']

    def test_webcam_stop_rejects_injection(self, client, mock_box_manager):
        """SECURITY: injection payload returns 400."""
        resp = client.post(
            '/api/box/test-box/webcam/stop',
            json={'net': "'; import os; os.system('rm -rf /'); '"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'Invalid net name' in data['error']

    def test_webcam_stop_unknown_box(self, client, mock_box_manager):
        """Unknown box returns 404."""
        resp = client.post(
            '/api/box/no-such-box/webcam/stop',
            json={'net': 'cam0'},
        )
        assert resp.status_code == 404
        data = resp.get_json()
        assert 'Box not found' in data['error']


# ---------------------------------------------------------------------------
# _run_script_on_box helper
# ---------------------------------------------------------------------------

class TestRunScriptOnBox:
    """Tests for the _run_script_on_box helper function."""

    @patch('routes.webcam.requests')
    def test_run_script_timeout(self, mock_requests, client, mock_box_manager):
        """Connection timeout is raised as requests.ConnectionError."""
        mock_requests.post.side_effect = requests.ConnectionError(
            'Connection timed out',
        )

        from routes.webcam import _run_script_on_box
        with pytest.raises(requests.ConnectionError):
            _run_script_on_box('192.0.2.1', b'print("hello")')
