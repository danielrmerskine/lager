# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/routes/dashboard.py.

Covers the dashboard index page, /api/statuses JSON endpoint, and
/api/lines endpoint -- including offline-box skipping, timeout handling,
fetch exceptions, sort order, and missing created_at fields.

All box interactions are mocked via BoxDataClient patches.
"""

from concurrent.futures import Future, TimeoutError
from unittest.mock import patch, MagicMock

import pytest


# The test boxes dict mirrors conftest.TEST_BOXES.
TEST_BOXES = {
    'test-box': {
        'ip': '192.0.2.1',
        'ssh_user': 'lager',
        'container': 'lager',
    },
    'test-box-2': {
        'ip': '192.0.2.2',
        'ssh_user': 'lager',
        'container': 'lager',
    },
}


# ---------------------------------------------------------------------------
# GET / -- dashboard index
# ---------------------------------------------------------------------------

class TestDashboardIndex:
    """Tests for the main dashboard page."""

    def test_index_renders(self, client, mock_box_manager):
        """GET / returns 200."""
        resp = client.get('/')
        assert resp.status_code == 200

    def test_index_contains_boxes(self, client, mock_box_manager):
        """Response body includes information about configured boxes."""
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'test-box' in resp.data


# ---------------------------------------------------------------------------
# GET /api/statuses
# ---------------------------------------------------------------------------

class TestStatusesEndpoint:
    """Tests for the /api/statuses JSON endpoint."""

    def test_statuses_returns_json(self, client, mock_box_manager):
        """GET /api/statuses returns a JSON dict with one entry per box."""
        with patch.object(mock_box_manager, 'check_all_statuses', return_value={
            'test-box': {'online': True},
            'test-box-2': {'online': True},
        }):
            resp = client.get('/api/statuses')

        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        assert 'test-box' in data
        assert 'test-box-2' in data

    def test_statuses_with_offline_box(self, client, mock_box_manager):
        """check_all_statuses correctly reports an offline box."""
        with patch.object(mock_box_manager, 'check_all_statuses', return_value={
            'test-box': {'online': True, 'container_running': True},
            'test-box-2': {'online': False, 'error': 'Connection refused'},
        }):
            resp = client.get('/api/statuses')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['test-box']['online'] is True
        assert data['test-box-2']['online'] is False
        assert 'Connection refused' in data['test-box-2']['error']


# ---------------------------------------------------------------------------
# GET /api/lines
# ---------------------------------------------------------------------------

class TestLinesApiEndpoint:
    """Tests for the /api/lines JSON endpoint."""

    @patch('routes.dashboard.BoxDataClient')
    def test_lines_api_returns_lines(self, mock_bdc_cls, client,
                                     mock_box_manager):
        """GET /api/lines returns a JSON list of lines from boxes."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_lines.return_value = [
            {'id': 1, 'name': 'Line A', 'created_at': '2025-06-01 00:00:00'},
        ]
        mock_instance.list_stations.return_value = [{'id': 10}]
        mock_instance.list_station_runs.return_value = []
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/api/lines')

        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]['name'] == 'Line A'
        assert 'box_id' in data[0]
        assert data[0]['station_count'] == 1

    @patch('routes.dashboard.BoxDataClient')
    def test_lines_api_skips_offline_boxes(self, mock_bdc_cls, client,
                                           mock_box_manager):
        """Boxes cached as offline are skipped -- BoxDataClient is not called for them."""
        # Mark test-box-2 as offline in the cache
        mock_box_manager._status_cache['test-box-2'] = {
            'status': {'online': False, 'error': 'Connection refused'},
            'timestamp': __import__('time').time(),
        }

        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_lines.return_value = [
            {'id': 1, 'name': 'Online Line', 'created_at': '2025-06-01'},
        ]
        mock_instance.list_stations.return_value = []
        mock_instance.list_station_runs.return_value = []
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/api/lines')

        assert resp.status_code == 200
        data = resp.get_json()
        # Only lines from the online box should appear
        for line in data:
            assert line['box_id'] != 'test-box-2'

    @patch('routes.dashboard.BoxDataClient')
    @patch('routes.dashboard.ThreadPoolExecutor')
    def test_lines_api_timeout_handling(self, mock_pool_cls, mock_bdc_cls,
                                        client, mock_box_manager):
        """When a ThreadPool future times out, partial results are returned."""
        # Set up two futures: one succeeds, one times out
        good_future = MagicMock()
        good_future.result.return_value = [
            {'id': 1, 'name': 'Good Line', 'box_id': 'test-box',
             '_source': 'box', 'created_at': '2025-06-01'},
        ]

        bad_future = MagicMock()
        bad_future.result.side_effect = TimeoutError('timed out')

        mock_pool = MagicMock()
        mock_pool.__enter__ = MagicMock(return_value=mock_pool)
        mock_pool.__exit__ = MagicMock(return_value=False)
        # submit returns futures keyed by box_id
        mock_pool.submit.side_effect = [good_future, bad_future]
        mock_pool_cls.return_value = mock_pool

        resp = client.get('/api/lines')

        assert resp.status_code == 200
        data = resp.get_json()
        # Only the non-timed-out result should be present
        assert len(data) == 1
        assert data[0]['name'] == 'Good Line'

    @patch('routes.dashboard.BoxDataClient')
    def test_lines_api_box_fetch_exception(self, mock_bdc_cls, client,
                                           mock_box_manager):
        """When _fetch_box_lines raises an exception, an empty list is returned for that box."""
        mock_instance = MagicMock()
        mock_instance.is_available.side_effect = Exception('network error')
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/api/lines')

        assert resp.status_code == 200
        data = resp.get_json()
        # _fetch_box_lines catches exceptions and returns [], so result is empty
        assert data == []

    @patch('routes.dashboard.BoxDataClient')
    def test_lines_sorted_by_created_at(self, mock_bdc_cls, client,
                                        mock_box_manager):
        """Results are sorted by created_at in descending order."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_lines.return_value = [
            {'id': 1, 'name': 'Old Line', 'created_at': '2025-01-01 00:00:00'},
            {'id': 2, 'name': 'New Line', 'created_at': '2025-06-15 12:00:00'},
            {'id': 3, 'name': 'Mid Line', 'created_at': '2025-03-10 06:00:00'},
        ]
        mock_instance.list_stations.return_value = []
        mock_instance.list_station_runs.return_value = []
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/api/lines')

        assert resp.status_code == 200
        data = resp.get_json()
        created_dates = [line.get('created_at', '') for line in data]
        assert created_dates == sorted(created_dates, reverse=True)

    @patch('routes.dashboard.BoxDataClient')
    def test_lines_missing_created_at(self, mock_bdc_cls, client,
                                      mock_box_manager):
        """Lines with missing created_at do not crash the sort."""
        mock_instance = MagicMock()
        mock_instance.is_available.return_value = True
        mock_instance.list_lines.return_value = [
            {'id': 1, 'name': 'No Date Line'},
            {'id': 2, 'name': 'Dated Line', 'created_at': '2025-06-01 00:00:00'},
        ]
        mock_instance.list_stations.return_value = []
        mock_instance.list_station_runs.return_value = []
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/api/lines')

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 2
        # The dated line should sort before the undated one (descending)
        names = [line['name'] for line in data]
        assert names.index('Dated Line') < names.index('No Date Line')
