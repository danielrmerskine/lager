# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Routes for per-box webcam viewing."""

import io
import json
import re

from flask import (
    Blueprint, render_template, flash, redirect, url_for, jsonify, Response,
)

from box_manager import get_box_manager, BOX_HTTP_PORT, _iter_v1_stream
import requests

# Allow only safe net names: alphanumeric, dash, underscore, dot.
_SAFE_NET_NAME_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')

bp = Blueprint('webcam', __name__)

# Script to read active webcam streams from the box
_WEBCAM_STREAMS_SCRIPT = b"""\
import json, os
path = '/etc/lager/webcam_streams.json'
if os.path.exists(path):
    with open(path) as f:
        print(f.read())
else:
    print('{}')
"""

# Script to list webcam nets from saved_nets.json
_WEBCAM_NETS_SCRIPT = b"""\
import json, os
path = '/etc/lager/saved_nets.json'
if not os.path.exists(path):
    path = os.path.expanduser('~/box/.lager/saved_nets.json')
if os.path.exists(path):
    with open(path) as f:
        nets = json.load(f)
    cams = [n for n in nets if n.get('role') in ('webcam', 'camera')]
    print(json.dumps(cams))
else:
    print('[]')
"""


def _run_script_on_box(box_ip, script_bytes):
    """Upload and run a tiny script on the box via HTTP POST /python."""
    url = f'http://{box_ip}:{BOX_HTTP_PORT}/python'
    script_file = io.BytesIO(script_bytes)
    files = [
        ('script', ('query.py', script_file, 'application/octet-stream')),
    ]
    resp = requests.post(
        url, files=files, stream=True,
        timeout=(5, 15),
        headers={'Connection': 'close'},
    )
    resp.raise_for_status()

    stdout_bytes = b''
    for fileno, data in _iter_v1_stream(resp):
        if fileno == 1:
            stdout_bytes += data
    return stdout_bytes.decode('utf-8', errors='replace').strip()


def _get_webcam_info(box_ip):
    """Fetch webcam nets and active stream info from a box."""
    webcam_nets = []
    streams = {}

    try:
        raw = _run_script_on_box(box_ip, _WEBCAM_NETS_SCRIPT)
        if raw:
            webcam_nets = json.loads(raw)
    except Exception:
        pass

    try:
        raw = _run_script_on_box(box_ip, _WEBCAM_STREAMS_SCRIPT)
        if raw and raw != '{}':
            streams = json.loads(raw)
    except Exception:
        pass

    return webcam_nets, streams


@bp.route('/box/<box_id>/webcam')
def webcam_viewer(box_id):
    """Show webcam nets and active streams for a box."""
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    webcam_nets, streams = _get_webcam_info(box['ip'])

    # Enrich each net with stream status
    for net in webcam_nets:
        net_name = net.get('name', '')
        stream_info = streams.get(net_name, {})
        net['streaming'] = bool(stream_info.get('port'))
        net['stream_port'] = stream_info.get('port')
        if net['streaming']:
            # Proxy through the webapp to avoid cross-origin issues
            net['stream_url'] = url_for(
                'webcam.webcam_proxy', box_id=box_id, net_name=net_name,
            )
            # Useful for debugging; not exposed in the UI by default
            net['direct_url'] = (
                f"http://{box['ip']}:{stream_info['port']}/stream"
            )

    return render_template(
        'webcam.html',
        box=box,
        box_id=box_id,
        webcam_nets=webcam_nets,
    )


@bp.route('/box/<box_id>/webcam/<net_name>/stream')
def webcam_proxy(box_id, net_name):
    """Proxy the MJPEG stream from a box through the webapp.

    This avoids browser cross-origin restrictions when the box is on a
    different network (e.g. Tailscale) than the user's browser.
    """
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        return 'Box not found', 404

    # Look up the stream port for this net
    try:
        raw = _run_script_on_box(box['ip'], _WEBCAM_STREAMS_SCRIPT)
        streams = json.loads(raw) if raw else {}
    except Exception:
        return 'Could not read stream info', 502

    stream_info = streams.get(net_name, {})
    port = stream_info.get('port')
    if not port:
        return 'Stream not active', 404

    direct_url = f"http://{box['ip']}:{port}/stream"

    def generate():
        try:
            with requests.get(direct_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception:
            pass

    return Response(
        generate(),
        content_type='multipart/x-mixed-replace; boundary=frame',
    )


@bp.route('/api/box/<box_id>/webcam/start', methods=['POST'])
def webcam_start(box_id):
    """Start webcam streaming for a net on a box."""
    from flask import request
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        return jsonify({'error': 'Box not found'}), 404

    data = request.get_json() or {}
    net_name = data.get('net')
    if not net_name:
        return jsonify({'error': 'net required'}), 400

    if not _SAFE_NET_NAME_RE.match(net_name):
        return jsonify({'error': 'Invalid net name'}), 400

    box_ip = box['ip']

    # Script that uses the actual webcam service API on the box
    start_script = f"""\
import json, sys
try:
    from lager.nets.net import Net
    from lager.automation.webcam import start_stream

    # Look up the net to get the video device
    nets = Net.list_saved()
    net = None
    for n in nets:
        if n.get('name') == '{net_name}':
            net = n
            break
    if not net:
        print(json.dumps({{'error': 'Net not found: {net_name}'}}))
        sys.exit(0)

    video_device = net.get('pin', '')
    if not video_device.startswith('/dev/'):
        video_device = '/dev/' + video_device

    result = start_stream('{net_name}', video_device, '{box_ip}')
    print(json.dumps({{
        'ok': True,
        'url': result.get('url', ''),
        'port': result.get('port', 0),
        'already_running': result.get('already_running', False),
    }}))
except Exception as e:
    print(json.dumps({{'error': str(e)}}))
""".encode()

    try:
        raw = _run_script_on_box(box_ip, start_script)
        result = json.loads(raw)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/box/<box_id>/webcam/stop', methods=['POST'])
def webcam_stop(box_id):
    """Stop webcam streaming for a net on a box."""
    from flask import request
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        return jsonify({'error': 'Box not found'}), 404

    data = request.get_json() or {}
    net_name = data.get('net')
    if not net_name:
        return jsonify({'error': 'net required'}), 400

    if not _SAFE_NET_NAME_RE.match(net_name):
        return jsonify({'error': 'Invalid net name'}), 400

    stop_script = f"""\
import json, sys
try:
    from lager.automation.webcam import stop_stream
    success = stop_stream('{net_name}')
    print(json.dumps({{'ok': success}}))
except Exception as e:
    print(json.dumps({{'error': str(e)}}))
""".encode()

    try:
        raw = _run_script_on_box(box['ip'], stop_script)
        result = json.loads(raw)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
