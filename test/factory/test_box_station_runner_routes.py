# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/routes/box_station_runner.py.

Covers the run_station page -- including successful render, unknown box,
unknown station, base64 decode errors, and step parsing from script content.

WebSocket routes (register_ws_routes) are NOT tested here because flask-sock
requires a real WebSocket connection that the Flask test client cannot provide.
Testing those routes requires an integration test with a real WebSocket client
(e.g. websocket-client or pytest-flask-socketio).

All box interactions are mocked via BoxDataClient patches.
"""

import base64

from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# GET /box/<box_name>/stations/<station_id>/run -- run station page
# ---------------------------------------------------------------------------

class TestRunStation:
    """Tests for the interactive step runner page."""

    @patch('routes.box_station_runner.BoxDataClient')
    def test_run_station_page_renders(self, mock_bdc_cls, client,
                                       mock_box_manager):
        """GET /box/test-box/stations/1/run returns 200."""
        mock_client = MagicMock()
        mock_client.get_station.return_value = {
            'id': 1,
            'name': 'Test Station',
            'line_id': 10,
        }
        mock_client.get_line.return_value = {
            'id': 10,
            'name': 'Test Line',
        }
        mock_client.list_station_scripts.return_value = []
        mock_bdc_cls.return_value = mock_client

        resp = client.get('/box/test-box/stations/1/run')
        assert resp.status_code == 200
        assert b'Test Station' in resp.data

    @patch('routes.box_station_runner.BoxDataClient')
    def test_run_station_unknown_box(self, mock_bdc_cls, client,
                                      mock_box_manager):
        """Unknown box flashes error and redirects to dashboard."""
        resp = client.get('/box/no-such-box/stations/1/run')
        assert resp.status_code == 302
        assert '/' in resp.headers['Location']

    @patch('routes.box_station_runner.BoxDataClient')
    def test_run_station_unknown_station(self, mock_bdc_cls, client,
                                          mock_box_manager):
        """get_station raising an exception flashes error and redirects."""
        mock_client = MagicMock()
        mock_client.get_station.side_effect = Exception('Station not found')
        mock_bdc_cls.return_value = mock_client

        resp = client.get('/box/test-box/stations/999/run')
        assert resp.status_code == 302
        assert '/' in resp.headers['Location']

    @patch('routes.box_station_runner.BoxDataClient')
    def test_run_station_base64_decode_error(self, mock_bdc_cls, client,
                                              mock_box_manager):
        """Bad base64 content is handled gracefully (content=b'')."""
        mock_client = MagicMock()
        mock_client.get_station.return_value = {
            'id': 1,
            'name': 'Station With Bad Script',
            'line_id': 10,
        }
        mock_client.get_line.return_value = {
            'id': 10,
            'name': 'Test Line',
        }
        mock_client.list_station_scripts.return_value = [{
            'id': 1,
            'filename': 'broken.py',
            'content_b64': 'NOT_VALID_BASE64!!!',
        }]
        mock_bdc_cls.return_value = mock_client

        resp = client.get('/box/test-box/stations/1/run')
        # Should not crash; falls back to content=b''
        assert resp.status_code == 200

    @patch('routes.box_station_runner.BoxDataClient')
    def test_run_station_step_parsing(self, mock_bdc_cls, client,
                                       mock_box_manager):
        """Steps are extracted from script content and passed to template."""
        # Build a valid Python script with Step classes
        script_source = (
            "from factory import Step\n"
            "\n"
            "class CheckVoltage(Step):\n"
            "    DisplayName = 'Check Voltage'\n"
            "    Description = 'Verify supply voltage is within range'\n"
            "\n"
            "class CheckCurrent(Step):\n"
            "    DisplayName = 'Check Current'\n"
            "    Description = 'Verify supply current is within range'\n"
            "\n"
            "STEPS = [CheckVoltage, CheckCurrent]\n"
        )
        content_b64 = base64.b64encode(script_source.encode()).decode('ascii')

        mock_client = MagicMock()
        mock_client.get_station.return_value = {
            'id': 1,
            'name': 'Voltage Station',
            'line_id': 10,
        }
        mock_client.get_line.return_value = {
            'id': 10,
            'name': 'Power Line',
        }
        mock_client.list_station_scripts.return_value = [{
            'id': 1,
            'filename': 'test_voltage.py',
            'content_b64': content_b64,
        }]
        mock_bdc_cls.return_value = mock_client

        resp = client.get('/box/test-box/stations/1/run')
        assert resp.status_code == 200
        # The parsed step names should appear in the rendered template
        assert b'Check Voltage' in resp.data
        assert b'Check Current' in resp.data
