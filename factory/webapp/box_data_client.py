# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""HTTP client for the box-side Dashboard REST API.

Mirrors the models.py interface but makes HTTP calls to the box's
/dashboard/* endpoints instead of querying local SQLite.
"""

import base64
import json

import requests


class BoxDataClient:
    """Client for a single box's dashboard API."""

    def __init__(self, box_ip, port=9000, timeout=10):
        self.base_url = f'http://{box_ip}:{port}/dashboard'
        self.timeout = timeout

    def _get(self, path, **params):
        resp = requests.get(
            f'{self.base_url}{path}',
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, data):
        resp = requests.post(
            f'{self.base_url}{path}',
            json=data,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path, data):
        resp = requests.put(
            f'{self.base_url}{path}',
            json=data,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path):
        resp = requests.delete(
            f'{self.base_url}{path}',
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # -- Health --

    def health(self):
        """Check if dashboard endpoints are available."""
        try:
            resp = requests.get(
                f'{self.base_url}/health',
                timeout=3,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {'available': False}

    def is_available(self):
        h = self.health()
        return h.get('available', False)

    # -- Lines --

    def list_lines(self):
        return self._get('/lines')

    def create_line(self, name, description='', **kwargs):
        return self._post('/lines', {
            'name': name,
            'description': description,
            **kwargs,
        })

    def get_line(self, line_id):
        return self._get(f'/lines/{line_id}')

    def update_line(self, line_id, **kwargs):
        return self._put(f'/lines/{line_id}', kwargs)

    def delete_line(self, line_id):
        return self._delete(f'/lines/{line_id}')

    # -- Stations --

    def list_stations(self, line_id):
        return self._get(f'/lines/{line_id}/stations')

    def create_station(self, line_id, name):
        return self._post('/stations', {
            'line_id': line_id,
            'name': name,
        })

    def get_station(self, station_id):
        return self._get(f'/stations/{station_id}')

    def update_station(self, station_id, **kwargs):
        return self._put(f'/stations/{station_id}', kwargs)

    def delete_station(self, station_id):
        return self._delete(f'/stations/{station_id}')

    # -- Station Scripts --

    def list_station_scripts(self, station_id):
        """List scripts. Content is returned as base64."""
        return self._get(f'/stations/{station_id}/scripts')

    def upload_station_scripts(self, station_id, file_list):
        """Upload scripts. file_list: list of (filename, content_bytes) tuples."""
        scripts = []
        for filename, content in file_list:
            if isinstance(content, str):
                content = content.encode()
            scripts.append({
                'filename': filename,
                'content_b64': base64.b64encode(content).decode('ascii'),
            })
        return self._post(f'/stations/{station_id}/scripts', {
            'scripts': scripts,
        })

    def remove_station_script(self, script_id):
        return self._delete(f'/scripts/{script_id}')

    def reorder_station_scripts(self, station_id, script_ids):
        return self._put(f'/stations/{station_id}/scripts/reorder', {
            'script_ids': script_ids,
        })

    # -- Station Runs --

    def list_station_runs(self, station_id=None, line_id=None, limit=100):
        params = {'limit': limit}
        if station_id is not None:
            params['station_id'] = station_id
        if line_id is not None:
            params['line_id'] = line_id
        return self._get('/runs', **params)

    def create_station_run(self, station_id):
        return self._post('/runs', {'station_id': station_id})

    def get_station_run(self, run_id):
        return self._get(f'/runs/{run_id}')

    def update_station_run(self, run_id, **kwargs):
        return self._put(f'/runs/{run_id}', kwargs)

    # -- Webcam --

    def list_webcam_streams(self):
        return self._get('/webcam/streams')
