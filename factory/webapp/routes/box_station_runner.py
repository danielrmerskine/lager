# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Box-scoped station runner route using BoxDataClient."""

import base64
import json
import queue
import threading

from flask import Blueprint, render_template, flash, redirect, url_for

from box_manager import get_box_manager
from box_data_client import BoxDataClient

bp = Blueprint('box_station_runner', __name__)


def _get_client(box_name):
    manager = get_box_manager()
    box = manager.get_box(box_name)
    if not box:
        return None, None
    return BoxDataClient(box['ip']), box


@bp.route('/box/<box_name>/stations/<int:station_id>/run')
def run_station(box_name, station_id):
    """Render the interactive step runner page for a box-scoped station."""
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        station = client.get_station(station_id)
    except Exception:
        flash('Station not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    if not station or station.get('error'):
        flash('Station not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        line = client.get_line(station['line_id'])
    except Exception:
        line = {'id': station['line_id'], 'name': '?'}

    try:
        scripts = client.list_station_scripts(station_id)
        # Decode content for step parsing
        for s in scripts:
            if 'content_b64' in s:
                try:
                    s['content'] = base64.b64decode(s['content_b64'])
                except Exception:
                    s['content'] = b''
    except Exception:
        scripts = []

    # Parse step metadata for sidebar display
    import step_parser
    steps = []
    for script in scripts:
        content = script.get('content', b'')
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        parsed = step_parser.parse_code(content)
        steps.extend(parsed)

    station['box_id'] = box_name

    return render_template(
        'station_run.html',
        station=station,
        line=line,
        scripts=scripts,
        steps=steps,
        box_name=box_name,
    )


def register_ws_routes(sock):
    """Register WebSocket routes with the flask-sock instance."""

    @sock.route('/ws/run/<int:run_id>')
    def step_run_ws(ws, run_id):
        import step_runner

        session = step_runner.get_session(run_id)
        if not session:
            ws.send(json.dumps({
                'type': 'error',
                'content': f'No active session for run {run_id}',
            }))
            return

        stop_event = threading.Event()

        # Reader thread: client WebSocket -> session.from_client queue
        def read_client():
            try:
                while not stop_event.is_set():
                    try:
                        data = ws.receive(timeout=1)
                    except Exception:
                        break
                    if data is None:
                        continue
                    try:
                        msg = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    session.from_client.put(msg)
            except Exception:
                pass

        reader = threading.Thread(target=read_client, daemon=True)
        reader.start()

        # Writer: session.to_client queue -> client WebSocket
        try:
            while True:
                try:
                    event = session.to_client.get(timeout=30)
                except queue.Empty:
                    try:
                        ws.send(json.dumps({'type': 'keepalive'}))
                    except Exception:
                        break
                    continue

                try:
                    ws.send(json.dumps(event))
                except Exception:
                    break

                if event.get('type') == 'lager-factory-complete':
                    break
        finally:
            stop_event.set()
            reader.join(timeout=2)
