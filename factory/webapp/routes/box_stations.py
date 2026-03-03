# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Box-scoped station CRUD and script management using BoxDataClient."""

import base64

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify)
from werkzeug.utils import secure_filename

from box_manager import get_box_manager
from box_data_client import BoxDataClient

bp = Blueprint('box_stations', __name__)


def _get_client(box_name):
    manager = get_box_manager()
    box = manager.get_box(box_name)
    if not box:
        return None, None
    return BoxDataClient(box['ip']), box


@bp.route('/box/<box_name>/lines/<int:line_id>/stations/new',
          methods=['GET', 'POST'])
def new_station(box_name, line_id):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        line = client.get_line(line_id)
    except Exception:
        flash('Line not found.', 'danger')
        return redirect(url_for('box_lines.list_lines'))

    if not line or line.get('error'):
        flash('Line not found.', 'danger')
        return redirect(url_for('box_lines.list_lines'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Station name is required.', 'danger')
            line['box_id'] = box_name
            return render_template('box_station_new.html', line=line,
                                   box_name=box_name)

        try:
            result = client.create_station(line_id, name)
            station_id = result.get('id')
            flash(f'Station "{name}" created.', 'success')
            return redirect(url_for('box_stations.station_detail',
                                    box_name=box_name,
                                    station_id=station_id))
        except Exception as e:
            flash(f'Failed to create station: {e}', 'danger')

    line['box_id'] = box_name
    return render_template('box_station_new.html', line=line,
                           box_name=box_name)


@bp.route('/box/<box_name>/stations/<int:station_id>')
def station_detail(box_name, station_id):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        station = client.get_station(station_id)
    except Exception:
        flash('Station not found.', 'danger')
        return redirect(url_for('box_lines.list_lines'))

    if not station or station.get('error'):
        flash('Station not found.', 'danger')
        return redirect(url_for('box_lines.list_lines'))

    try:
        line = client.get_line(station['line_id'])
    except Exception:
        line = {'id': station['line_id'], 'name': '?'}

    try:
        scripts = client.list_station_scripts(station_id)
        # Decode content for display
        for s in scripts:
            if 'content_b64' in s:
                try:
                    s['content'] = base64.b64decode(s['content_b64'])
                except Exception:
                    s['content'] = b''
    except Exception:
        scripts = []

    try:
        runs = client.list_station_runs(station_id=station_id, limit=20)
    except Exception:
        runs = []

    station['box_id'] = box_name

    return render_template('box_station_detail.html', station=station,
                           line=line, scripts=scripts, runs=runs,
                           box_name=box_name)


@bp.route('/box/<box_name>/stations/<int:station_id>/edit',
          methods=['GET', 'POST'])
def edit_station(box_name, station_id):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        station = client.get_station(station_id)
    except Exception:
        flash('Station not found.', 'danger')
        return redirect(url_for('box_lines.list_lines'))

    if not station or station.get('error'):
        flash('Station not found.', 'danger')
        return redirect(url_for('box_lines.list_lines'))

    try:
        line = client.get_line(station['line_id'])
    except Exception:
        line = {'id': station['line_id'], 'name': '?'}

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Station name is required.', 'danger')
            station['box_id'] = box_name
            return render_template('box_station_edit.html', station=station,
                                   line=line, box_name=box_name)

        try:
            client.update_station(station_id, name=name)
            flash(f'Station "{name}" updated.', 'success')
        except Exception as e:
            flash(f'Failed to update station: {e}', 'danger')
        return redirect(url_for('box_stations.station_detail',
                                box_name=box_name, station_id=station_id))

    station['box_id'] = box_name
    return render_template('box_station_edit.html', station=station,
                           line=line, box_name=box_name)


@bp.route('/box/<box_name>/stations/<int:station_id>/delete',
          methods=['POST'])
def delete_station(box_name, station_id):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        station = client.get_station(station_id)
        line_id = station.get('line_id')
        client.delete_station(station_id)
        flash('Station deleted.', 'success')
    except Exception as e:
        flash(f'Failed to delete station: {e}', 'danger')
        line_id = None

    if line_id:
        return redirect(url_for('box_lines.line_detail',
                                box_name=box_name, line_id=line_id))
    return redirect(url_for('box_lines.list_lines'))


@bp.route('/box/<box_name>/stations/<int:station_id>/scripts/upload',
          methods=['POST'])
def upload_scripts(box_name, station_id):
    client, box = _get_client(box_name)
    if not client:
        return jsonify({'error': 'Box not found'}), 404

    if 'files' not in request.files:
        flash('No files provided.', 'danger')
        return redirect(url_for('box_stations.station_detail',
                                box_name=box_name, station_id=station_id))

    files = request.files.getlist('files')
    file_list = []
    for f in files:
        if not f.filename or not f.filename.endswith('.py'):
            continue
        safe_name = secure_filename(f.filename)
        if not safe_name or not safe_name.endswith('.py'):
            continue
        content = f.read()
        file_list.append((safe_name, content))

    if file_list:
        try:
            client.upload_station_scripts(station_id, file_list)
            flash(f'Uploaded {len(file_list)} script(s).', 'success')
        except Exception as e:
            flash(f'Failed to upload scripts: {e}', 'danger')
    else:
        flash('No valid .py files uploaded.', 'warning')

    return redirect(url_for('box_stations.station_detail',
                            box_name=box_name, station_id=station_id))


@bp.route('/box/<box_name>/stations/<int:station_id>/scripts/'
          '<int:script_id>/delete', methods=['POST'])
def delete_script(box_name, station_id, script_id):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        client.remove_station_script(script_id)
        flash('Script removed.', 'success')
    except Exception as e:
        flash(f'Failed to remove script: {e}', 'danger')

    return redirect(url_for('box_stations.station_detail',
                            box_name=box_name, station_id=station_id))


@bp.route('/box/<box_name>/stations/<int:station_id>/scripts/reorder',
          methods=['POST'])
def reorder_scripts(box_name, station_id):
    client, box = _get_client(box_name)
    if not client:
        return jsonify({'error': 'Box not found'}), 404

    data = request.get_json()
    if not data or 'script_ids' not in data:
        return jsonify({'error': 'script_ids required'}), 400

    try:
        client.reorder_station_scripts(station_id, data['script_ids'])
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
