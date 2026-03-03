# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Box-scoped line CRUD routes using BoxDataClient."""

from concurrent.futures import ThreadPoolExecutor

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash)

from box_manager import get_box_manager
from box_data_client import BoxDataClient

bp = Blueprint('box_lines', __name__)


def _get_client(box_name):
    """Get a BoxDataClient for the named box, or None."""
    manager = get_box_manager()
    box = manager.get_box(box_name)
    if not box:
        return None, None
    return BoxDataClient(box['ip']), box


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


@bp.route('/lines')
def list_lines():
    """Show lines page. Lines are loaded asynchronously via /api/lines."""
    manager = get_box_manager()
    boxes = manager.boxes
    return render_template('lines.html', boxes=boxes)


@bp.route('/box/<box_name>/lines/new', methods=['GET', 'POST'])
def new_line(box_name):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Line name is required.', 'danger')
            return render_template('box_line_new.html', box=box,
                                   box_name=box_name)

        try:
            result = client.create_line(name, description)
            line_id = result.get('id')
            flash(f'Line "{name}" created.', 'success')
            return redirect(url_for('box_lines.line_detail',
                                    box_name=box_name, line_id=line_id))
        except Exception as e:
            flash(f'Failed to create line: {e}', 'danger')
            return render_template('box_line_new.html', box=box,
                                   box_name=box_name)

    return render_template('box_line_new.html', box=box, box_name=box_name)


@bp.route('/box/<box_name>/lines/<int:line_id>')
def line_detail(box_name, line_id):
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

    try:
        stations = client.list_stations(line_id)
    except Exception:
        stations = []

    # Attach script count to each station
    for st in stations:
        try:
            scripts = client.list_station_scripts(st['id'])
            st['script_count'] = len(scripts)
        except Exception:
            st['script_count'] = 0

    line['box_id'] = box_name

    return render_template('box_line_detail.html', line=line,
                           stations=stations, box=box, box_name=box_name)


@bp.route('/box/<box_name>/lines/<int:line_id>/edit', methods=['GET', 'POST'])
def edit_line(box_name, line_id):
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
        description = request.form.get('description', '').strip()

        if not name:
            flash('Line name is required.', 'danger')
            line['box_id'] = box_name
            return render_template('box_line_edit.html', line=line,
                                   box=box, box_name=box_name)

        try:
            client.update_line(line_id, name=name, description=description)
            flash(f'Line "{name}" updated.', 'success')
        except Exception as e:
            flash(f'Failed to update line: {e}', 'danger')
        return redirect(url_for('box_lines.line_detail',
                                box_name=box_name, line_id=line_id))

    line['box_id'] = box_name
    return render_template('box_line_edit.html', line=line, box=box,
                           box_name=box_name)


@bp.route('/box/<box_name>/lines/<int:line_id>/delete', methods=['POST'])
def delete_line(box_name, line_id):
    client, box = _get_client(box_name)
    if not client:
        flash('Box not found.', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        client.delete_line(line_id)
        flash('Line deleted.', 'success')
    except Exception as e:
        flash(f'Failed to delete line: {e}', 'danger')

    return redirect(url_for('box_lines.list_lines'))
