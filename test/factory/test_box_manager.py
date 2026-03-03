# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/box_manager.py.

Covers _iter_v1_stream parsing, BoxManager CRUD and caching, SSH client
creation, HTTP-based status checks, parallel status fetching, and cache
invalidation.  All external dependencies (paramiko, requests) are mocked.
"""

import time
import threading
from unittest.mock import patch, MagicMock

import pytest

# The test boxes dict mirrors conftest.TEST_BOXES.  Defined here so we do
# not need to import from conftest (which pytest loads as a plugin, not as
# a regular module).
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
# Helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    """Minimal stand-in for ``requests.Response`` that supports iter_content.

    *chunks* is a list of ``bytes`` objects.  Each call to ``iter_content``
    yields them in order, simulating chunked transfer from the network.
    """

    def __init__(self, chunks):
        self._chunks = chunks

    def iter_content(self, chunk_size=4096):
        yield from self._chunks


def _get_iter_v1_stream():
    """Import and return ``_iter_v1_stream`` from the webapp module."""
    from box_manager import _iter_v1_stream
    return _iter_v1_stream


# ---------------------------------------------------------------------------
# _iter_v1_stream
# ---------------------------------------------------------------------------

class TestIterV1Stream:

    def test_single_stdout_message(self):
        """A single stdout frame is parsed correctly."""
        parse = _get_iter_v1_stream()
        resp = FakeResponse([b'1 5 hello'])
        messages = list(parse(resp))
        assert messages == [(1, b'hello')]

    def test_multiple_messages(self):
        """Multiple frames in a single chunk are all yielded."""
        parse = _get_iter_v1_stream()
        data = b'1 5 hello2 6 stderr'
        resp = FakeResponse([data])
        messages = list(parse(resp))
        assert messages == [(1, b'hello'), (2, b'stderr')]

    def test_exit_code_message(self):
        """An exit-code frame (fileno=-1) is parsed correctly."""
        parse = _get_iter_v1_stream()
        resp = FakeResponse([b'-1 1 0'])
        messages = list(parse(resp))
        assert messages == [(-1, b'0')]

    def test_partial_buffering_across_chunks(self):
        """A frame split across two network chunks is reassembled."""
        parse = _get_iter_v1_stream()
        # "1 11 hello world" split after 'hell'
        chunk1 = b'1 11 hell'
        chunk2 = b'o world'
        resp = FakeResponse([chunk1, chunk2])
        messages = list(parse(resp))
        assert messages == [(1, b'hello world')]

    def test_empty_stream(self):
        """An empty response yields no messages."""
        parse = _get_iter_v1_stream()
        resp = FakeResponse([])
        messages = list(parse(resp))
        assert messages == []

    def test_header_split_across_chunks(self):
        """The header itself can be split across chunks."""
        parse = _get_iter_v1_stream()
        # "1 5 hello" split inside the header
        chunk1 = b'1 '
        chunk2 = b'5 hello'
        resp = FakeResponse([chunk1, chunk2])
        messages = list(parse(resp))
        assert messages == [(1, b'hello')]

    def test_multiple_chunks_multiple_messages(self):
        """Several frames spread across several chunks."""
        parse = _get_iter_v1_stream()
        chunk1 = b'1 3 abc'
        chunk2 = b'2 3 def-1 1 0'
        resp = FakeResponse([chunk1, chunk2])
        messages = list(parse(resp))
        assert messages == [(1, b'abc'), (2, b'def'), (-1, b'0')]


# ---------------------------------------------------------------------------
# BoxManager -- basic accessors
# ---------------------------------------------------------------------------

class TestBoxManagerAccessors:

    def test_get_box_found(self, mock_box_manager):
        """get_box returns the config dict for a known box."""
        box = mock_box_manager.get_box('test-box')
        assert box is not None
        assert box['ip'] == '192.0.2.1'

    def test_get_box_not_found(self, mock_box_manager):
        """get_box returns None for an unknown box id."""
        assert mock_box_manager.get_box('no-such-box') is None

    def test_boxes_property_returns_copy(self, mock_box_manager):
        """The boxes property returns a copy -- mutating it does not affect
        the manager's internal state."""
        copy = mock_box_manager.boxes
        copy['injected'] = {'ip': '0.0.0.0'}
        assert 'injected' not in mock_box_manager.boxes


# ---------------------------------------------------------------------------
# get_ssh_client
# ---------------------------------------------------------------------------

class TestGetSshClient:

    @patch('box_manager.paramiko.SSHClient')
    def test_returns_client_for_known_box(self, MockSSHClient, mock_box_manager):
        """get_ssh_client returns a connected paramiko client for a known box."""
        mock_client = MagicMock()
        MockSSHClient.return_value = mock_client

        result = mock_box_manager.get_ssh_client('test-box')

        assert result is mock_client
        mock_client.set_missing_host_key_policy.assert_called_once()
        mock_client.connect.assert_called_once_with(
            hostname='192.0.2.1',
            username='lager',
            timeout=10,
        )

    def test_raises_for_unknown_box(self, mock_box_manager):
        """get_ssh_client raises ValueError for an unknown box."""
        with pytest.raises(ValueError, match='Unknown box'):
            mock_box_manager.get_ssh_client('no-such-box')


# ---------------------------------------------------------------------------
# check_status -- caching behaviour
# ---------------------------------------------------------------------------

class TestCheckStatusCaching:

    def test_cache_hit(self, mock_box_manager):
        """When a recent status is cached, _fetch_status is NOT called."""
        cached_status = {'online': True, 'cached': True}
        mock_box_manager._status_cache['test-box'] = {
            'status': cached_status,
            'timestamp': time.time(),  # fresh
        }

        with patch.object(mock_box_manager, '_fetch_status') as mock_fetch:
            result = mock_box_manager.check_status('test-box')

        mock_fetch.assert_not_called()
        assert result is cached_status

    def test_cache_miss_calls_fetch(self, mock_box_manager):
        """When nothing is cached, _fetch_status is called and the result
        is stored in the cache."""
        expected = {'online': True, 'fresh': True}
        with patch.object(mock_box_manager, '_fetch_status', return_value=expected) as mock_fetch:
            result = mock_box_manager.check_status('test-box')

        mock_fetch.assert_called_once_with('test-box')
        assert result == expected
        assert 'test-box' in mock_box_manager._status_cache

    def test_stale_cache_triggers_refetch(self, mock_box_manager):
        """An expired cache entry causes a fresh _fetch_status call."""
        stale_status = {'online': False, 'stale': True}
        mock_box_manager._status_cache['test-box'] = {
            'status': stale_status,
            'timestamp': time.time() - 60,  # well past TTL
        }

        fresh_status = {'online': True, 'fresh': True}
        with patch.object(mock_box_manager, '_fetch_status', return_value=fresh_status):
            result = mock_box_manager.check_status('test-box')

        assert result == fresh_status


# ---------------------------------------------------------------------------
# _fetch_status -- HTTP interactions
# ---------------------------------------------------------------------------

class TestFetchStatus:

    def test_unknown_box_returns_offline(self, mock_box_manager):
        """_fetch_status returns offline status for an unknown box id."""
        status = mock_box_manager._fetch_status('nonexistent')
        assert status['online'] is False
        assert 'Unknown box' in status['error']

    @patch('box_manager.requests.get')
    def test_health_200_success(self, mock_get, mock_box_manager):
        """A healthy box returns online + container_running."""
        health_resp = MagicMock(status_code=200)
        version_resp = MagicMock(status_code=200)
        version_resp.json.return_value = {'box_version': '1.2.3'}
        dashboard_resp = MagicMock(status_code=200)
        dashboard_resp.json.return_value = {'available': True}

        mock_get.side_effect = [health_resp, version_resp, dashboard_resp]

        with patch.object(mock_box_manager, '_fetch_nets_via_http', return_value=(3, ['labjack'], True)):
            status = mock_box_manager._fetch_status('test-box')

        assert status['online'] is True
        assert status['container_running'] is True
        assert status['version'] == '1.2.3'
        assert status['net_count'] == 3
        assert status['instruments'] == ['labjack']
        assert status['has_webcam'] is True
        assert status['dashboard_available'] is True

    @patch('box_manager.requests.get')
    def test_health_500_container_not_running(self, mock_get, mock_box_manager):
        """A non-200 /health response means the container is not running."""
        health_resp = MagicMock(status_code=500)
        mock_get.return_value = health_resp

        status = mock_box_manager._fetch_status('test-box')

        assert status['online'] is True
        assert status['container_running'] is False
        assert status['net_count'] == 0

    @patch('box_manager.requests.get')
    def test_connection_error_offline(self, mock_get, mock_box_manager):
        """A ConnectionError means the box is offline."""
        import requests
        mock_get.side_effect = requests.ConnectionError('refused')

        status = mock_box_manager._fetch_status('test-box')

        assert status['online'] is False
        assert 'Connection refused' in status['error']

    @patch('box_manager.requests.get')
    def test_timeout_offline(self, mock_get, mock_box_manager):
        """A Timeout exception means the box is offline."""
        import requests
        mock_get.side_effect = requests.Timeout('timed out')

        status = mock_box_manager._fetch_status('test-box')

        assert status['online'] is False
        assert 'Timeout' in status['error']

    @patch('box_manager.requests.get')
    def test_generic_exception_offline(self, mock_get, mock_box_manager):
        """An unexpected exception is captured and reported."""
        mock_get.side_effect = RuntimeError('something broke')

        status = mock_box_manager._fetch_status('test-box')

        assert status['online'] is False
        assert 'something broke' in status['error']


# ---------------------------------------------------------------------------
# check_all_statuses
# ---------------------------------------------------------------------------

class TestCheckAllStatuses:

    def test_returns_dict_for_all_boxes(self, mock_box_manager):
        """check_all_statuses returns a result for every configured box."""
        fake_status = {'online': True, 'container_running': True}
        with patch.object(mock_box_manager, 'check_status', return_value=fake_status):
            results = mock_box_manager.check_all_statuses()

        assert set(results.keys()) == set(TEST_BOXES.keys())
        for box_id in TEST_BOXES:
            assert results[box_id] == fake_status

    def test_handles_timeout_in_future(self, mock_box_manager):
        """If a future raises an exception, the box is marked offline."""
        def slow_check(box_id):
            if box_id == 'test-box-2':
                raise TimeoutError('took too long')
            return {'online': True}

        with patch.object(mock_box_manager, 'check_status', side_effect=slow_check):
            results = mock_box_manager.check_all_statuses()

        assert results['test-box'] == {'online': True}
        assert results['test-box-2']['online'] is False
        assert 'took too long' in results['test-box-2']['error']


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------

class TestInvalidateCache:

    def test_invalidate_single_box(self, mock_box_manager):
        """invalidate_cache(box_id) removes only that box's entry."""
        mock_box_manager._status_cache['test-box'] = {
            'status': {'online': True},
            'timestamp': time.time(),
        }
        mock_box_manager._status_cache['test-box-2'] = {
            'status': {'online': True},
            'timestamp': time.time(),
        }

        mock_box_manager.invalidate_cache('test-box')

        assert 'test-box' not in mock_box_manager._status_cache
        assert 'test-box-2' in mock_box_manager._status_cache

    def test_invalidate_all_boxes(self, mock_box_manager):
        """invalidate_cache() with no argument clears the entire cache."""
        mock_box_manager._status_cache['test-box'] = {
            'status': {'online': True},
            'timestamp': time.time(),
        }
        mock_box_manager._status_cache['test-box-2'] = {
            'status': {'online': True},
            'timestamp': time.time(),
        }

        mock_box_manager.invalidate_cache()

        assert mock_box_manager._status_cache == {}


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestIterV1StreamEdgeCases:

    def test_zero_length_message(self):
        """A message with length=0 yields empty data."""
        parse = _get_iter_v1_stream()
        resp = FakeResponse([b'1 0 '])
        messages = list(parse(resp))
        # Length 0 means 0 bytes of data
        assert messages == [(1, b'')]

    def test_unknown_fileno(self):
        """fileno=3 (not 1, 2, or -1) is still parsed."""
        parse = _get_iter_v1_stream()
        resp = FakeResponse([b'3 4 test'])
        messages = list(parse(resp))
        assert messages == [(3, b'test')]

    def test_very_large_length(self):
        """A message claiming large length reads available data."""
        parse = _get_iter_v1_stream()
        data = b'1 1000 ' + b'x' * 1000
        resp = FakeResponse([data])
        messages = list(parse(resp))
        assert len(messages) == 1
        assert messages[0] == (1, b'x' * 1000)


class TestCheckStatusEdgeCases:

    def test_unknown_box_check_status(self, mock_box_manager):
        """check_status for unknown box calls _fetch_status."""
        with patch.object(mock_box_manager, '_fetch_status',
                         return_value={'online': False, 'error': 'Unknown box'}) as m:
            result = mock_box_manager.check_status('nonexistent')

        m.assert_called_once_with('nonexistent')
        assert result['online'] is False


class TestCheckAllStatusesEdgeCases:

    def test_partial_failure(self, mock_box_manager):
        """Some boxes timeout while others succeed."""
        call_count = [0]

        def mixed_check(box_id):
            call_count[0] += 1
            if box_id == 'test-box':
                return {'online': True}
            raise TimeoutError('slow box')

        with patch.object(mock_box_manager, 'check_status', side_effect=mixed_check):
            results = mock_box_manager.check_all_statuses()

        assert results['test-box'] == {'online': True}
        assert results['test-box-2']['online'] is False


class TestInvalidateCacheEdgeCases:

    def test_invalidate_nonexistent_box(self, mock_box_manager):
        """Invalidating a box not in cache is a no-op."""
        mock_box_manager._status_cache.clear()
        # Should not raise
        mock_box_manager.invalidate_cache('nonexistent')
        assert mock_box_manager._status_cache == {}
