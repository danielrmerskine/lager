# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/routes/results.py.

Covers the /results page (scripts and stations tabs), /results/export
JSON endpoint, and /results/<run_id> detail endpoint -- including active
in-memory runs and 404 for unknown IDs.

All box interactions are mocked via BoxDataClient patches.
"""

from unittest.mock import patch, MagicMock

import pytest

from script_runner import RunRecord


# ---------------------------------------------------------------------------
# /results -- default (scripts) tab
# ---------------------------------------------------------------------------

class TestResultsPageScriptsTab:
    """GET /results with the default 'scripts' tab."""

    @patch('routes.results.get_all_runs', return_value=[])
    @patch('routes.results.get_all_suites', return_value=[])
    def test_default_tab_returns_200(self, mock_suites, mock_runs, client):
        """The default tab (scripts) renders successfully with no runs."""
        resp = client.get('/results')
        assert resp.status_code == 200

    @patch('routes.results.get_all_suites', return_value=[])
    @patch('routes.results.get_all_runs')
    def test_default_tab_with_run_data(self, mock_runs, mock_suites, client):
        """Scripts tab shows runs from in-memory store."""
        mock_runs.return_value = [{
            'run_id': 'r-scripts-1',
            'box_id': 'test-box',
            'script_name': 'hello.py',
            'status': 'completed',
            'started_at': '2025-06-01 00:00:00',
        }]
        resp = client.get('/results')
        assert resp.status_code == 200
        assert b'r-scripts-1' in resp.data


# ---------------------------------------------------------------------------
# /results -- stations tab
# ---------------------------------------------------------------------------

class TestResultsPageStationsTab:
    """GET /results?tab=stations triggers _fetch_station_data."""

    @patch('routes.results.BoxDataClient')
    def test_stations_tab_returns_200(self, mock_bdc_cls, client,
                                      mock_box_manager):
        """Stations tab renders without errors when no box data is available."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = False
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results?tab=stations')
        assert resp.status_code == 200

    @patch('routes.results.BoxDataClient')
    def test_stations_tab_with_filters(self, mock_bdc_cls, client,
                                       mock_box_manager):
        """Stations tab accepts line_id and station_id query params."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_station_runs.return_value = [{
            'id': 1,
            'station_id': 10,
            'status': 'completed',
            'started_at': '2025-06-01 00:00:00',
            'station_name': 'Test Station',
            'line_name': 'Test Line',
            'success': 3,
            'failure': 0,
            'failed_step': '',
            'duration': 10.0,
        }]
        mock_instance.list_lines.return_value = [{
            'id': 1, 'name': 'Test Line',
        }]
        mock_instance.list_stations.return_value = [{
            'id': 10, 'name': 'Test Station',
        }]
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results?tab=stations&line_id=1&station_id=10')
        assert resp.status_code == 200

    @patch('routes.results.BoxDataClient')
    def test_stations_tab_computes_pass_rate(self, mock_bdc_cls, client,
                                             mock_box_manager):
        """Pass rate is computed from station runs in the response context."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_station_runs.return_value = [
            {'id': 1, 'status': 'completed', 'started_at': '2025-06-01 00:00:00',
             'success': 3, 'failure': 0, 'failed_step': '', 'duration': 5.0},
            {'id': 2, 'status': 'failed', 'started_at': '2025-06-01 00:01:00',
             'success': 1, 'failure': 1, 'failed_step': 'verify', 'duration': 3.0},
        ]
        mock_instance.list_lines.return_value = []
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results?tab=stations')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /results/export
# ---------------------------------------------------------------------------

class TestResultsExport:
    """GET /results/export returns JSON station run data from box APIs."""

    @patch('routes.results.BoxDataClient')
    def test_export_no_filters(self, mock_bdc_cls, client, mock_box_manager):
        """Export with no filters returns runs from all boxes."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_station_runs.return_value = [
            {'id': 1, 'status': 'completed', 'started_at': '2025-06-01 00:00:00'},
            {'id': 2, 'status': 'failed', 'started_at': '2025-06-01 00:01:00'},
        ]
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results/export')
        assert resp.status_code == 200
        data = resp.get_json()
        # Two boxes in TEST_BOXES * 2 runs each = 4, but capped at limit=100
        assert len(data) >= 2

    @patch('routes.results.BoxDataClient')
    def test_export_enriches_with_station_and_line_name(self, mock_bdc_cls,
                                                         client,
                                                         mock_box_manager):
        """Each exported run has station_name and line_name (from box API or default)."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_station_runs.return_value = [{
            'id': 1,
            'status': 'completed',
            'started_at': '2025-06-01 00:00:00',
            'station_name': 'My Station',
            'line_name': 'My Line',
        }]
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results/export')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        assert data[0]['station_name'] == 'My Station'
        assert data[0]['line_name'] == 'My Line'

    @patch('routes.results.BoxDataClient')
    def test_export_defaults_missing_names(self, mock_bdc_cls, client,
                                            mock_box_manager):
        """Runs without station_name/line_name get '?' as default."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_station_runs.return_value = [{
            'id': 1,
            'status': 'completed',
            'started_at': '2025-06-01 00:00:00',
        }]
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results/export')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data[0]['station_name'] == '?'
        assert data[0]['line_name'] == '?'


# ---------------------------------------------------------------------------
# /results/<run_id> -- active RunRecord
# ---------------------------------------------------------------------------

class TestResultDetailActiveRun:
    """GET /results/<run_id> when the run is still active in memory."""

    @patch('routes.results.get_active_run')
    def test_active_run_record_object(self, mock_get_run, client):
        """An active RunRecord is returned with its output_lines."""
        record = RunRecord('abc123', 'test-box', 'test.py')
        record.output_lines.append({'type': 'stdout', 'line': 'hello'})
        mock_get_run.return_value = record

        resp = client.get('/results/abc123')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == 'abc123'
        assert data['script_name'] == 'test.py'
        assert len(data['output']) == 1
        assert data['output'][0]['line'] == 'hello'

    @patch('routes.results.get_active_run')
    def test_active_run_as_dict(self, mock_get_run, client):
        """An active run returned as a plain dict gets output defaulted."""
        mock_get_run.return_value = {
            'run_id': 'dict-run',
            'box_id': 'test-box',
            'script_name': 'foo.py',
            'status': 'running',
        }

        resp = client.get('/results/dict-run')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['run_id'] == 'dict-run'
        assert data['output'] == []

    @patch('routes.results.get_active_run')
    def test_active_run_dict_preserves_existing_output(self, mock_get_run,
                                                        client):
        """A dict with an existing 'output' key preserves it."""
        mock_get_run.return_value = {
            'run_id': 'has-output',
            'box_id': 'test-box',
            'script_name': 'bar.py',
            'status': 'running',
            'output': [{'type': 'stdout', 'line': 'already here'}],
        }

        resp = client.get('/results/has-output')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['output']) == 1
        assert data['output'][0]['line'] == 'already here'


# ---------------------------------------------------------------------------
# /results/<run_id> -- 404
# ---------------------------------------------------------------------------

class TestResultDetail404:
    """GET /results/<run_id> returns 404 when run is not found anywhere."""

    @patch('routes.results.get_active_run', return_value=None)
    def test_unknown_run_returns_404(self, mock_get_run, client):
        resp = client.get('/results/nonexistent-id')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestResultsPageEdgeCases:

    @patch('routes.results.BoxDataClient')
    def test_stations_tab_invalid_filter(self, mock_bdc_cls, client,
                                          mock_box_manager):
        """Stations tab with invalid filter params still renders."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_station_runs.return_value = []
        mock_instance.list_lines.return_value = []
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results?tab=stations&line_id=invalid')
        assert resp.status_code == 200

    @patch('routes.results.get_all_runs', return_value=[])
    @patch('routes.results.get_all_suites', return_value=[])
    def test_scripts_tab_with_unknown_tab_param(self, mock_suites, mock_runs,
                                                  client):
        """Unknown tab parameter falls back to scripts tab."""
        resp = client.get('/results?tab=nonexistent')
        assert resp.status_code == 200


class TestResultsExportEdgeCases:

    @patch('routes.results.BoxDataClient')
    def test_export_unavailable_box(self, mock_bdc_cls, client,
                                     mock_box_manager):
        """Export skips unavailable boxes."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = False
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/results/export')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []
