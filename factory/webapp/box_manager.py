# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
import io
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import paramiko
import requests

from config import Config

# Port used by the lager-python-box HTTP service inside the container.
# Exposed on the host via Docker port mapping.
BOX_HTTP_PORT = 5000

# Port used by the box dashboard service.
BOX_DASHBOARD_PORT = 9000

# Tiny script uploaded to /python endpoint to list nets as JSON.
_LIST_NETS_SCRIPT = b"""\
import sys, json, os
path = '/etc/lager/saved_nets.json'
if not os.path.exists(path):
    path = os.path.expanduser('~/box/.lager/saved_nets.json')
if os.path.exists(path):
    with open(path) as f:
        print(f.read())
else:
    print('[]')
"""


def _iter_v1_stream(response):
    """Parse the V1 streaming output format from the box /python endpoint.

    Format per message: ``<fileno> <length> <content>``
    where fileno is 1 (stdout), 2 (stderr), or -1 (exit code).
    Yields (fileno, data_bytes) tuples.
    """
    buf = b''
    for chunk in response.iter_content(chunk_size=4096):
        buf += chunk
        while buf:
            # Need at least "<fileno> <length> " header
            # Find first space (after fileno)
            sp1 = buf.find(b' ')
            if sp1 == -1:
                break
            # Find second space (after length)
            sp2 = buf.find(b' ', sp1 + 1)
            if sp2 == -1:
                break
            try:
                fileno_str = buf[:sp1].decode()
                fileno = int(fileno_str) if fileno_str != '-' else -1
                # Handle "-1" as two chars: '-' then '1'
                if fileno_str.startswith('-') and len(fileno_str) > 1:
                    fileno = int(fileno_str)
                length = int(buf[sp1 + 1:sp2].decode())
            except (ValueError, UnicodeDecodeError):
                break
            content_start = sp2 + 1
            content_end = content_start + length
            if len(buf) < content_end:
                break  # need more data
            data = buf[content_start:content_end]
            yield (fileno, data)
            buf = buf[content_end:]


class BoxManager:
    """Manages connections to Lager boxes and caches their status."""

    def __init__(self, boxes=None):
        self._boxes = boxes or Config.BOXES
        self._status_cache = {}  # box_id -> {status dict, timestamp}
        self._cache_ttl = 30  # seconds
        self._lock = threading.Lock()

    @property
    def boxes(self):
        return dict(self._boxes)

    def get_box(self, box_id):
        return self._boxes.get(box_id)

    def get_ssh_client(self, box_id):
        """Return a connected paramiko SSHClient for the given box.

        Uses AutoAddPolicy to accept box host keys automatically.
        """
        box = self._boxes.get(box_id)
        if not box:
            raise ValueError(f"Unknown box: {box_id}")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=box['ip'],
            username=box.get('ssh_user', box.get('user', 'lagerdata')),
            timeout=10,
        )
        return client

    def check_status(self, box_id):
        """Check a box's status via HTTP, with SSH fallback for net details.

        Results are cached for 30 seconds.
        """
        with self._lock:
            cached = self._status_cache.get(box_id)
            if cached and (time.time() - cached['timestamp']) < self._cache_ttl:
                return cached['status']

        status = self._fetch_status(box_id)

        with self._lock:
            self._status_cache[box_id] = {
                'status': status,
                'timestamp': time.time(),
            }
        return status

    def _fetch_status(self, box_id):
        """Check box status via HTTP endpoints on port 5000.

        Uses GET /health to confirm the box is online and the container
        is running, then GET /cli-version for version info. Falls back
        to SSH for net/instrument details.
        """
        box = self._boxes.get(box_id)
        if not box:
            return {'online': False, 'error': 'Unknown box'}

        ip = box['ip']
        base_url = f'http://{ip}:{BOX_HTTP_PORT}'

        # Step 1: Check if box is reachable and container is running
        try:
            resp = requests.get(
                f'{base_url}/health',
                timeout=5,
                headers={'Cache-Control': 'no-cache'},
            )
            if resp.status_code != 200:
                return {
                    'online': True,
                    'container_running': False,
                    'net_count': 0,
                    'instruments': [],
                }
        except requests.ConnectionError:
            return {'online': False, 'error': 'Connection refused'}
        except requests.Timeout:
            return {'online': False, 'error': 'Timeout'}
        except Exception as e:
            return {'online': False, 'error': str(e)}

        # Step 2: Get version info
        version = None
        try:
            resp = requests.get(
                f'{base_url}/cli-version',
                timeout=5,
                headers={'Cache-Control': 'no-cache'},
            )
            if resp.status_code == 200:
                data = resp.json()
                version = data.get('box_version')
        except Exception:
            pass

        # Step 3: Fetch net/instrument details via HTTP /python endpoint
        net_count = 0
        instruments = []
        has_webcam = False
        try:
            net_count, instruments, has_webcam = self._fetch_nets_via_http(ip)
        except Exception:
            pass

        # Step 4: Check if box has dashboard endpoints
        dashboard_available = False
        try:
            resp = requests.get(
                f'http://{ip}:{BOX_DASHBOARD_PORT}/dashboard/health',
                timeout=3,
            )
            if resp.status_code == 200:
                data = resp.json()
                dashboard_available = data.get('available', False)
        except Exception:
            pass

        result = {
            'online': True,
            'container_running': True,
            'net_count': net_count,
            'instruments': instruments,
            'has_webcam': has_webcam,
            'dashboard_available': dashboard_available,
        }
        if version:
            result['version'] = version
        return result

    def _fetch_nets_via_http(self, ip):
        """Fetch net count and instrument list via HTTP POST /python.

        Uploads a tiny script that reads saved_nets.json and prints it.
        Parses the V1 streaming response to extract stdout.

        Returns (net_count, instrument_list). Raises on failure.
        """
        url = f'http://{ip}:{BOX_HTTP_PORT}/python'
        script_file = io.BytesIO(_LIST_NETS_SCRIPT)
        files = [
            ('script', ('list_nets.py', script_file, 'application/octet-stream')),
        ]
        resp = requests.post(
            url, files=files, stream=True,
            timeout=(5, 15),
            headers={'Connection': 'close'},
        )
        resp.raise_for_status()

        # Parse V1 streaming response: "<fileno> <length> <content>"
        stdout_bytes = b''
        for fileno, data in _iter_v1_stream(resp):
            if fileno == 1:  # stdout
                stdout_bytes += data

        nets_json = stdout_bytes.decode('utf-8', errors='replace').strip()
        if not nets_json or nets_json == '[]':
            return 0, []

        nets = json.loads(nets_json)
        instruments = set()
        has_webcam = False
        for n in nets:
            inst = n.get('instrument')
            if inst:
                instruments.add(inst)
            if n.get('role') in ('webcam', 'camera'):
                has_webcam = True
        return len(nets), sorted(instruments), has_webcam

    def check_all_statuses(self):
        """Check status of all boxes in parallel."""
        results = {}
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {
                pool.submit(self.check_status, box_id): box_id
                for box_id in self._boxes
            }
            for future in futures:
                box_id = futures[future]
                try:
                    results[box_id] = future.result(timeout=15)
                except Exception as e:
                    results[box_id] = {'online': False, 'error': str(e)}
        return results

    def invalidate_cache(self, box_id=None):
        """Clear cached status for one or all boxes."""
        with self._lock:
            if box_id:
                self._status_cache.pop(box_id, None)
            else:
                self._status_cache.clear()


# Module-level singleton
_manager = None
_manager_lock = threading.Lock()


def get_box_manager():
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = BoxManager()
    return _manager
