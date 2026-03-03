# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, render_template, jsonify

from box_manager import get_box_manager
from box_data_client import BoxDataClient

bp = Blueprint('dashboard', __name__)


def _fetch_box_lines(box_id, box):
    """Fetch lines from a single box's data API."""
    try:
        client = BoxDataClient(box['ip'])
        if not client.is_available():
            return []
        lines = client.list_lines()
        for line in lines:
            line['box_id'] = box_id
            line['_source'] = 'box'
            try:
                stations = client.list_stations(line['id'])
                line['station_count'] = len(stations)
            except Exception:
                line['station_count'] = 0
            try:
                runs = client.list_station_runs(line_id=line['id'], limit=1)
                line['last_run'] = runs[0] if runs else None
            except Exception:
                line['last_run'] = None
        return lines
    except Exception:
        return []


@bp.route('/')
def index():
    manager = get_box_manager()
    boxes = manager.boxes
    return render_template('dashboard.html', boxes=boxes)


@bp.route('/api/statuses')
def statuses():
    """AJAX endpoint returning current status of all boxes."""
    manager = get_box_manager()
    statuses = manager.check_all_statuses()
    return jsonify(statuses)


@bp.route('/api/lines')
def lines_api():
    """AJAX endpoint returning lines from all boxes."""
    manager = get_box_manager()
    boxes = manager.boxes

    # Use cached statuses to skip offline boxes (avoids slow timeouts)
    cached = {
        bid: entry['status']
        for bid, entry in manager._status_cache.items()
    }

    lines = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {}
        for box_id, box in boxes.items():
            status = cached.get(box_id, {})
            if status and not status.get('online', True):
                continue
            futures[pool.submit(_fetch_box_lines, box_id, box)] = box_id
        for future in futures:
            try:
                result = future.result(timeout=5)
                lines.extend(result)
            except Exception:
                pass

    lines.sort(key=lambda l: l.get('created_at', ''), reverse=True)
    return jsonify(lines)
