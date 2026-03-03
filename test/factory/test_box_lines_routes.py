# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/routes/box_lines.py.

Covers all box_lines blueprint endpoints: listing lines, creating new lines,
viewing line detail, editing lines, and deleting lines.

All box interactions are mocked via BoxDataClient patches at the route module
level, since _get_client() instantiates BoxDataClient inside the handler.
"""

from unittest.mock import patch, MagicMock

import pytest


def _mock_box_data_client(**method_returns):
    """Build a mock BoxDataClient class and instance with preconfigured returns.

    Usage::

        mock_cls, mock_inst = _mock_box_data_client(
            list_lines=[{'id': 1, 'name': 'L1'}],
            get_line={'id': 1, 'name': 'L1'},
        )
    """
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    for method, return_val in method_returns.items():
        getattr(mock_instance, method).return_value = return_val
    mock_cls.return_value = mock_instance
    return mock_cls, mock_instance


# ---------------------------------------------------------------------------
# GET /lines
# ---------------------------------------------------------------------------

class TestListLines:
    """Tests for the /lines endpoint that shows all lines."""

    @patch('routes.box_lines.BoxDataClient')
    def test_list_lines_page(self, mock_bdc_cls, client, mock_box_manager):
        """GET /lines returns 200 and renders the lines page."""
        mock_instance = MagicMock()
        mock_bdc_cls.return_value = mock_instance

        resp = client.get('/lines')
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET/POST /box/<box_name>/lines/new
# ---------------------------------------------------------------------------

class TestNewLine:
    """Tests for creating a new line via the /box/<box_name>/lines/new endpoint."""

    @patch('routes.box_lines.BoxDataClient')
    def test_new_line_form(self, mock_bdc_cls, client, mock_box_manager):
        """GET /box/test-box/lines/new returns 200 with the new-line form."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/lines/new')
        assert resp.status_code == 200

    @patch('routes.box_lines.BoxDataClient')
    def test_create_line_success(self, mock_bdc_cls, client, mock_box_manager):
        """POST with valid name creates a line and redirects to its detail page."""
        mock_cls, mock_inst = _mock_box_data_client(
            create_line={'id': 42, 'name': 'New Line'},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/new', data={
            'name': 'New Line',
            'description': 'A test line',
        })
        assert resp.status_code == 302
        assert '/box/test-box/lines/42' in resp.headers['Location']
        mock_inst.create_line.assert_called_once_with('New Line', 'A test line')

    @patch('routes.box_lines.BoxDataClient')
    def test_create_line_empty_name(self, mock_bdc_cls, client,
                                    mock_box_manager):
        """POST with empty name shows a flash error and re-renders the form (200)."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/new', data={
            'name': '   ',
            'description': '',
        })
        assert resp.status_code == 200
        assert b'Line name is required.' in resp.data

    @patch('routes.box_lines.BoxDataClient')
    def test_create_line_api_failure(self, mock_bdc_cls, client,
                                     mock_box_manager):
        """POST when client.create_line() raises shows an error flash."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_inst.create_line.side_effect = RuntimeError('connection refused')
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/new', data={
            'name': 'Broken Line',
            'description': '',
        })
        # Route re-renders the form on failure
        assert resp.status_code == 200
        assert b'Failed to create line' in resp.data

    @patch('routes.box_lines.BoxDataClient')
    def test_unknown_box_redirects(self, mock_bdc_cls, client,
                                   mock_box_manager):
        """Unknown box_name redirects to the dashboard."""
        resp = client.get('/box/nonexistent-box/lines/new')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/')


# ---------------------------------------------------------------------------
# GET /box/<box_name>/lines/<line_id>
# ---------------------------------------------------------------------------

class TestLineDetail:
    """Tests for the line detail endpoint."""

    @patch('routes.box_lines.BoxDataClient')
    def test_line_detail_renders(self, mock_bdc_cls, client, mock_box_manager):
        """GET /box/test-box/lines/1 renders with line data and stations."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Main Line', 'description': 'desc'},
            list_stations=[
                {'id': 10, 'name': 'Station A'},
                {'id': 11, 'name': 'Station B'},
            ],
            list_station_scripts=[
                {'id': 100, 'filename': 'a.py'},
            ],
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/lines/1')
        assert resp.status_code == 200

    @patch('routes.box_lines.BoxDataClient')
    def test_line_detail_station_script_count_failure(self, mock_bdc_cls,
                                                       client,
                                                       mock_box_manager):
        """When list_station_scripts() fails, station script_count defaults to 0."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Main Line', 'description': 'desc'},
            list_stations=[{'id': 10, 'name': 'Station A'}],
        )
        mock_inst.list_station_scripts.side_effect = RuntimeError('timeout')
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/lines/1')
        assert resp.status_code == 200

    @patch('routes.box_lines.BoxDataClient')
    def test_line_not_found(self, mock_bdc_cls, client, mock_box_manager):
        """When get_line raises, the user is redirected to the lines list."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_inst.get_line.side_effect = RuntimeError('not found')
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/lines/999')
        assert resp.status_code == 302
        assert '/lines' in resp.headers['Location']


# ---------------------------------------------------------------------------
# GET/POST /box/<box_name>/lines/<line_id>/edit
# ---------------------------------------------------------------------------

class TestEditLine:
    """Tests for the edit-line endpoint."""

    @patch('routes.box_lines.BoxDataClient')
    def test_edit_line_get(self, mock_bdc_cls, client, mock_box_manager):
        """GET renders the edit form with the current line data."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Old Name', 'description': 'old desc'},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.get('/box/test-box/lines/1/edit')
        assert resp.status_code == 200

    @patch('routes.box_lines.BoxDataClient')
    def test_edit_line_post_success(self, mock_bdc_cls, client,
                                    mock_box_manager):
        """POST with valid data updates the line and redirects to detail."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Old Name', 'description': 'old desc'},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/1/edit', data={
            'name': 'New Name',
            'description': 'new desc',
        })
        assert resp.status_code == 302
        assert '/box/test-box/lines/1' in resp.headers['Location']
        mock_inst.update_line.assert_called_once_with(
            1, name='New Name', description='new desc',
        )

    @patch('routes.box_lines.BoxDataClient')
    def test_edit_line_empty_name(self, mock_bdc_cls, client,
                                  mock_box_manager):
        """POST with empty name shows flash error and re-renders the form."""
        mock_cls, mock_inst = _mock_box_data_client(
            get_line={'id': 1, 'name': 'Old Name', 'description': 'old desc'},
        )
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/1/edit', data={
            'name': '',
            'description': 'new desc',
        })
        assert resp.status_code == 200
        assert b'Line name is required.' in resp.data


# ---------------------------------------------------------------------------
# POST /box/<box_name>/lines/<line_id>/delete
# ---------------------------------------------------------------------------

class TestDeleteLine:
    """Tests for deleting a line."""

    @patch('routes.box_lines.BoxDataClient')
    def test_delete_line_success(self, mock_bdc_cls, client, mock_box_manager):
        """POST deletes the line and redirects to the lines list."""
        mock_cls, mock_inst = _mock_box_data_client()
        mock_bdc_cls.return_value = mock_inst

        resp = client.post('/box/test-box/lines/1/delete')
        assert resp.status_code == 302
        assert '/lines' in resp.headers['Location']
        mock_inst.delete_line.assert_called_once_with(1)

    @patch('routes.box_lines.BoxDataClient')
    def test_delete_line_unknown_box(self, mock_bdc_cls, client,
                                     mock_box_manager):
        """Unknown box redirects to the dashboard."""
        resp = client.post('/box/nonexistent-box/lines/1/delete')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/')
