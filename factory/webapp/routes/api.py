# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
from flask import Blueprint, Response, jsonify, request

from script_runner import (
    start_run, get_run, get_all_runs, stream_output,
    start_suite_run, get_suite, get_all_suites, stream_suite_output,
)
from box_manager import get_box_manager
from box_data_client import BoxDataClient
import script_store

bp = Blueprint('api', __name__, url_prefix='/api')


# ---------- Existing single-run endpoints ----------

@bp.route('/run', methods=['POST'])
def api_run():
    """Start a script run. Expects JSON with box_id and script."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    box_id = data.get('box_id')
    script = data.get('script', '')
    script_name = data.get('script_name', 'script.py')

    if not box_id:
        return jsonify({'error': 'box_id required'}), 400
    if not script.strip():
        return jsonify({'error': 'script cannot be empty'}), 400

    manager = get_box_manager()
    if not manager.get_box(box_id):
        return jsonify({'error': f'Unknown box: {box_id}'}), 404

    run_id = start_run(box_id, script, script_name)
    return jsonify({'run_id': run_id})


@bp.route('/stream/<run_id>')
def api_stream(run_id):
    """SSE endpoint streaming live output of a run."""
    record = get_run(run_id)
    if not record:
        return jsonify({'error': 'Unknown run'}), 404

    return Response(
        stream_output(run_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@bp.route('/runs')
def api_runs():
    """Return list of all runs."""
    return jsonify(get_all_runs())


@bp.route('/run/<run_id>')
def api_run_detail(run_id):
    """Return details of a specific run, including output log."""
    record = get_run(run_id)
    if record:
        if isinstance(record, dict):
            result = dict(record)
            result.setdefault('output', [])
            return jsonify(result)
        result = record.to_dict()
        result['output'] = record.output_lines
        return jsonify(result)

    return jsonify({'error': 'Unknown run'}), 404


@bp.route('/run/<run_id>/cancel', methods=['POST'])
def api_cancel(run_id):
    """Cancel a running script."""
    record = get_run(run_id)
    if not record:
        return jsonify({'error': 'Unknown run'}), 404
    if isinstance(record, dict):
        return jsonify({'error': 'Run is not active'}), 400
    if record.status != 'running':
        return jsonify({'error': 'Run is not active'}), 400
    record.cancel()
    return jsonify({'status': 'cancelling'})


# ---------- Script management endpoints ----------

@bp.route('/scripts')
def api_scripts():
    """List uploaded scripts in execution order."""
    return jsonify(script_store.list_scripts())


@bp.route('/scripts/upload', methods=['POST'])
def api_scripts_upload():
    """Upload one or more .py files (multipart form)."""
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400

    files = request.files.getlist('files')
    added = []
    errors = []
    for f in files:
        if not f.filename:
            continue
        try:
            script_store.add_script(f.filename, f.read())
            added.append(f.filename)
        except ValueError as e:
            errors.append({'file': f.filename, 'error': str(e)})

    return jsonify({'added': added, 'errors': errors})


@bp.route('/scripts/<filename>', methods=['DELETE'])
def api_scripts_delete(filename):
    """Remove an uploaded script."""
    script_store.remove_script(filename)
    return jsonify({'status': 'ok'})


@bp.route('/scripts/reorder', methods=['POST'])
def api_scripts_reorder():
    """Set new execution order. Expects JSON array of filenames."""
    data = request.get_json()
    if not data or 'order' not in data:
        return jsonify({'error': 'JSON body with "order" array required'}), 400
    try:
        script_store.reorder_scripts(data['order'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'status': 'ok'})


# ---------- Suite execution endpoints ----------

@bp.route('/run-suite', methods=['POST'])
def api_run_suite():
    """Start sequential execution of all uploaded scripts."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    box_id = data.get('box_id')
    if not box_id:
        return jsonify({'error': 'box_id required'}), 400

    manager = get_box_manager()
    if not manager.get_box(box_id):
        return jsonify({'error': f'Unknown box: {box_id}'}), 404

    scripts = script_store.list_scripts()
    if not scripts:
        return jsonify({'error': 'No scripts uploaded'}), 400

    script_names = [s['name'] for s in scripts]
    suite_id = start_suite_run(box_id, script_names)
    return jsonify({'suite_id': suite_id})


@bp.route('/stream-suite/<suite_id>')
def api_stream_suite(suite_id):
    """SSE endpoint streaming live suite events."""
    suite = get_suite(suite_id)
    if not suite:
        return jsonify({'error': 'Unknown suite'}), 404

    return Response(
        stream_suite_output(suite_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@bp.route('/suites')
def api_suites():
    """Return list of all suite runs."""
    return jsonify(get_all_suites())


@bp.route('/suite/<suite_id>/cancel', methods=['POST'])
def api_cancel_suite(suite_id):
    """Cancel a running suite."""
    suite = get_suite(suite_id)
    if not suite:
        return jsonify({'error': 'Unknown suite'}), 404
    if isinstance(suite, dict):
        return jsonify({'error': 'Suite is not active'}), 400
    if suite.status != 'running':
        return jsonify({'error': 'Suite is not active'}), 400
    suite.cancel()
    return jsonify({'status': 'cancelling'})


# ---------- Station Run API endpoints ----------

@bp.route('/station-run/start', methods=['POST'])
def api_station_run_start():
    """Start an interactive station run. Returns run_id and step metadata."""
    import base64

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    station_id = data.get('station_id')
    box_id = data.get('box_id')
    if not station_id:
        return jsonify({'error': 'station_id required'}), 400
    if not box_id:
        return jsonify({'error': 'box_id required'}), 400

    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        return jsonify({'error': f'Unknown box: {box_id}'}), 404

    client = BoxDataClient(box['ip'])

    try:
        station = client.get_station(station_id)
    except Exception:
        return jsonify({'error': 'Station not found'}), 404
    if not station or station.get('error'):
        return jsonify({'error': 'Station not found'}), 404

    try:
        scripts = client.list_station_scripts(station_id)
    except Exception:
        return jsonify({'error': 'Failed to fetch scripts'}), 500
    if not scripts:
        return jsonify({'error': 'No scripts in station'}), 400

    # Decode base64 content
    for s in scripts:
        if 'content_b64' in s:
            try:
                s['content'] = base64.b64decode(s['content_b64'])
            except Exception:
                s['content'] = b''

    # Parse scripts for step metadata
    import step_parser
    steps = []
    for script in scripts:
        content = script.get('content', b'')
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        parsed = step_parser.parse_code(content)
        steps.extend(parsed)

    # Create run record on box
    try:
        result = client.create_station_run(station_id)
        run_id = result.get('id')
    except Exception as e:
        return jsonify({'error': f'Failed to create run: {e}'}), 500

    # Start the step runner session (pass pre-fetched scripts to avoid
    # Flask context errors in the daemon thread)
    import step_runner
    step_runner.start_session(run_id, station_id, box_id, scripts=scripts)

    return jsonify({'run_id': run_id, 'steps': steps})


@bp.route('/station-run/<int:run_id>/stop', methods=['POST'])
def api_station_run_stop(run_id):
    """Save completed run data and cleanup."""
    import json as json_mod
    from datetime import datetime, timezone

    data = request.get_json() or {}
    box_id = data.get('box_id')

    stopped_at = data.get('stopped_at') or datetime.now(
        timezone.utc
    ).strftime('%Y-%m-%d %H:%M:%S')

    # Persist to box API if box_id provided
    if box_id:
        manager = get_box_manager()
        box = manager.get_box(box_id)
        if box:
            try:
                client = BoxDataClient(box['ip'])
                event_log = data.get('event_log', [])
                if not isinstance(event_log, str):
                    event_log = json_mod.dumps(event_log)
                client.update_station_run(
                    run_id,
                    status=data.get('status', 'completed'),
                    event_log=event_log,
                    stdout=data.get('stdout', ''),
                    stderr=data.get('stderr', ''),
                    success=data.get('success', 0),
                    failure=data.get('failure', 0),
                    failed_step=data.get('failed_step', ''),
                    stopped_at=stopped_at,
                    duration=data.get('duration', 0),
                )
            except Exception:
                pass

    import step_runner
    step_runner.cleanup_session(run_id)

    return jsonify({'status': 'ok'})
