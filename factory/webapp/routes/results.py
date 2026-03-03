# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, render_template, jsonify, request

from box_manager import get_box_manager
from box_data_client import BoxDataClient

bp = Blueprint('results', __name__)


def _fetch_station_data(line_id, station_id, limit):
    """Fetch station run data and filter metadata in a single parallel pass.

    For each box, fetches both runs and lines in one call to avoid
    redundant round-trips.
    """
    manager = get_box_manager()
    boxes = manager.boxes

    def _fetch_from_box(box_id, box):
        """Fetch runs + lines from a single box."""
        try:
            client = BoxDataClient(box['ip'])
            if not client.is_available():
                return {'runs': [], 'lines': []}
            runs = client.list_station_runs(
                station_id=station_id, line_id=line_id, limit=limit
            )
            for r in runs:
                r['_box_id'] = box_id
            lines = client.list_lines()
            for l in lines:
                l['box_id'] = box_id
            return {'runs': runs, 'lines': lines}
        except Exception:
            return {'runs': [], 'lines': []}

    all_runs = []
    all_lines = []

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_fetch_from_box, bid, b): bid
            for bid, b in boxes.items()
        }
        for future in futures:
            try:
                result = future.result(timeout=10)
                all_runs.extend(result['runs'])
                all_lines.extend(result['lines'])
            except Exception:
                pass

    all_runs.sort(key=lambda r: r.get('started_at', ''), reverse=True)
    all_runs = all_runs[:limit]

    for run in all_runs:
        run.setdefault('station_name', '?')
        run.setdefault('line_name', '?')

    total = len(all_runs)
    passed = sum(1 for r in all_runs if r.get('status') == 'completed')
    pass_rate = round(passed / total * 100) if total > 0 else 0

    # Fetch stations for the selected line (single request, only if filtered)
    stations = []
    if line_id:
        for line in all_lines:
            if line.get('id') == line_id:
                box_id = line.get('box_id')
                box = manager.get_box(box_id) if box_id else None
                if box:
                    try:
                        client = BoxDataClient(box['ip'])
                        stations = client.list_stations(line_id)
                    except Exception:
                        pass
                break

    return dict(
        station_runs=all_runs,
        lines=all_lines,
        stations=stations,
        selected_line_id=line_id,
        selected_station_id=station_id,
        selected_limit=limit,
        total=total,
        passed=passed,
        pass_rate=pass_rate,
    )


@bp.route('/results')
def results_page():
    line_id = request.args.get('line_id', type=int)
    station_id = request.args.get('station_id', type=int)
    limit = request.args.get('limit', 100, type=int)

    ctx = _fetch_station_data(line_id, station_id, limit)
    return render_template('results.html', **ctx)


@bp.route('/results/export')
def results_export():
    """Export filtered station run data as JSON from box APIs."""
    line_id = request.args.get('line_id', type=int)
    station_id = request.args.get('station_id', type=int)
    limit = request.args.get('limit', 100, type=int)

    manager = get_box_manager()
    boxes = manager.boxes
    all_runs = []

    def _fetch_from_box(box_id, box):
        try:
            client = BoxDataClient(box['ip'])
            if not client.is_available():
                return []
            runs = client.list_station_runs(
                station_id=station_id, line_id=line_id, limit=limit
            )
            for r in runs:
                r['_box_id'] = box_id
                r.setdefault('station_name', '?')
                r.setdefault('line_name', '?')
            return runs
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_fetch_from_box, bid, b): bid
            for bid, b in boxes.items()
        }
        for future in futures:
            try:
                all_runs.extend(future.result(timeout=10))
            except Exception:
                pass

    all_runs.sort(key=lambda r: r.get('started_at', ''), reverse=True)
    all_runs = all_runs[:limit]

    return jsonify(all_runs)
