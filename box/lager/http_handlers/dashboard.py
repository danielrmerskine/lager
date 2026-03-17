# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Dashboard HTTP handlers for the Lager Box HTTP server.

Provides REST endpoints for managing dashboard data (lines, stations,
scripts, runs) stored locally on the box in SQLite.

Follows the register_*_routes(app) pattern from supply.py.
"""

import base64
import json
import logging
import os

from flask import Flask, request, jsonify

logger = logging.getLogger(__name__)


def register_dashboard_routes(app: Flask) -> None:
    """Register dashboard REST routes with the Flask app."""

    from lager.dashboard_db import (
        init_db,
        create_line, get_line, list_lines, update_line, delete_line,
        create_station, get_station, list_stations, update_station,
        delete_station, add_station_script, list_station_scripts,
        get_station_script, remove_station_script, reorder_station_scripts,
        create_station_run, get_station_run, list_station_runs,
        update_station_run,
    )

    # Initialize DB on registration
    init_db()

    # -- Health / capability detection --

    @app.route('/dashboard/health', methods=['GET'])
    def dashboard_health():
        return jsonify({'available': True, 'version': '1.0'})

    # -- Lines --

    @app.route('/dashboard/lines', methods=['GET'])
    def dashboard_list_lines():
        return jsonify(list_lines())

    @app.route('/dashboard/lines', methods=['POST'])
    def dashboard_create_line():
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'name required'}), 400
        line_id = create_line(
            name,
            description=data.get('description', ''),
            source_type=data.get('source_type', 'upload'),
            git_repo=data.get('git_repo', ''),
            git_ref=data.get('git_ref', ''),
        )
        return jsonify({'id': line_id}), 201

    @app.route('/dashboard/lines/<int:line_id>', methods=['GET'])
    def dashboard_get_line(line_id):
        line = get_line(line_id)
        if not line:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(line)

    @app.route('/dashboard/lines/<int:line_id>', methods=['PUT'])
    def dashboard_update_line(line_id):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        update_line(line_id, **data)
        return jsonify({'status': 'ok'})

    @app.route('/dashboard/lines/<int:line_id>', methods=['DELETE'])
    def dashboard_delete_line(line_id):
        delete_line(line_id)
        return jsonify({'status': 'ok'})

    # -- Stations --

    @app.route('/dashboard/lines/<int:line_id>/stations', methods=['GET'])
    def dashboard_list_stations(line_id):
        return jsonify(list_stations(line_id))

    @app.route('/dashboard/stations', methods=['POST'])
    def dashboard_create_station():
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        line_id = data.get('line_id')
        name = data.get('name', '').strip()
        if not line_id or not name:
            return jsonify({'error': 'line_id and name required'}), 400
        station_id = create_station(line_id, name)
        return jsonify({'id': station_id}), 201

    @app.route('/dashboard/stations/<int:station_id>', methods=['GET'])
    def dashboard_get_station(station_id):
        station = get_station(station_id)
        if not station:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(station)

    @app.route('/dashboard/stations/<int:station_id>', methods=['PUT'])
    def dashboard_update_station(station_id):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        update_station(station_id, **data)
        return jsonify({'status': 'ok'})

    @app.route('/dashboard/stations/<int:station_id>', methods=['DELETE'])
    def dashboard_delete_station(station_id):
        delete_station(station_id)
        return jsonify({'status': 'ok'})

    # -- Station Scripts --

    @app.route('/dashboard/stations/<int:station_id>/scripts', methods=['GET'])
    def dashboard_list_scripts(station_id):
        scripts = list_station_scripts(station_id)
        # Serialize content as base64 for JSON transport
        for s in scripts:
            content = s.get('content')
            if isinstance(content, (bytes, memoryview)):
                s['content_b64'] = base64.b64encode(bytes(content)).decode('ascii')
            elif isinstance(content, str):
                s['content_b64'] = base64.b64encode(content.encode()).decode('ascii')
            # Remove raw content from JSON response
            s.pop('content', None)
        return jsonify(scripts)

    @app.route('/dashboard/stations/<int:station_id>/scripts', methods=['POST'])
    def dashboard_upload_scripts(station_id):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        scripts_data = data.get('scripts', [])
        added = []
        for s in scripts_data:
            filename = s.get('filename', '')
            content_b64 = s.get('content_b64', '')
            if not filename or not content_b64:
                continue
            content = base64.b64decode(content_b64)
            script_id = add_station_script(station_id, filename, content)
            added.append({'id': script_id, 'filename': filename})
        return jsonify({'added': added}), 201

    @app.route('/dashboard/scripts/<int:script_id>', methods=['DELETE'])
    def dashboard_delete_script(script_id):
        remove_station_script(script_id)
        return jsonify({'status': 'ok'})

    @app.route('/dashboard/stations/<int:station_id>/scripts/reorder',
               methods=['PUT'])
    def dashboard_reorder_scripts(station_id):
        data = request.get_json()
        if not data or 'script_ids' not in data:
            return jsonify({'error': 'script_ids required'}), 400
        reorder_station_scripts(station_id, data['script_ids'])
        return jsonify({'status': 'ok'})

    # -- Station Runs --

    @app.route('/dashboard/runs', methods=['GET'])
    def dashboard_list_runs():
        station_id = request.args.get('station_id', type=int)
        line_id = request.args.get('line_id', type=int)
        limit = request.args.get('limit', 100, type=int)
        runs = list_station_runs(
            station_id=station_id, line_id=line_id, limit=limit
        )
        return jsonify(runs)

    @app.route('/dashboard/runs', methods=['POST'])
    def dashboard_create_run():
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        station_id = data.get('station_id')
        if not station_id:
            return jsonify({'error': 'station_id required'}), 400
        run_id = create_station_run(station_id)
        return jsonify({'id': run_id}), 201

    @app.route('/dashboard/runs/<int:run_id>', methods=['GET'])
    def dashboard_get_run(run_id):
        run = get_station_run(run_id)
        if not run:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(run)

    @app.route('/dashboard/runs/<int:run_id>', methods=['PUT'])
    def dashboard_update_run(run_id):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        update_station_run(run_id, **data)
        return jsonify({'status': 'ok'})

    # -- Webcam streams --

    @app.route('/dashboard/webcam/streams', methods=['GET'])
    def dashboard_webcam_streams():
        streams_path = '/etc/lager/webcam_streams.json'
        if os.path.exists(streams_path):
            with open(streams_path) as f:
                return jsonify(json.load(f))
        return jsonify({})

    @app.route('/dashboard/webcam/start', methods=['POST'])
    def dashboard_webcam_start():
        from lager.nets.net import Net
        from lager.automation.webcam import start_stream

        data = request.get_json() or {}
        net_name = data.get('net')
        if not net_name:
            return jsonify({'error': 'net is required', 'status': 'error'}), 400

        # Resolve video device from net config
        try:
            nets = Net.list_saved()
            net = None
            for n in nets:
                if n.get('name') == net_name:
                    net = n
                    break
            if not net:
                return jsonify({'error': f"Net '{net_name}' not found", 'status': 'error'}), 404
            if net.get('role') != 'webcam':
                return jsonify({'error': f"Net '{net_name}' is not a webcam net", 'status': 'error'}), 400
            video_device = net.get('pin')
            if not video_device:
                return jsonify({'error': f"Net '{net_name}' has no video device configured", 'status': 'error'}), 400
            if not video_device.startswith('/dev/'):
                video_device = f'/dev/{video_device}'
        except Exception as e:
            logger.exception('Failed to resolve video device for net %s', net_name)
            return jsonify({'error': str(e), 'status': 'error'}), 500

        # Use the request host as box_ip so stream URLs are correct
        box_ip = request.host.split(':')[0]

        try:
            result = start_stream(net_name, video_device, box_ip)
            return jsonify({'status': 'ok', **result})
        except Exception as e:
            logger.exception('Failed to start webcam stream for %s', net_name)
            return jsonify({'error': str(e), 'status': 'error'}), 500

    @app.route('/dashboard/webcam/stop', methods=['POST'])
    def dashboard_webcam_stop():
        from lager.automation.webcam import stop_stream

        data = request.get_json() or {}
        net_name = data.get('net')
        if not net_name:
            return jsonify({'error': 'net is required', 'status': 'error'}), 400

        try:
            stopped = stop_stream(net_name)
            if stopped:
                return jsonify({'status': 'ok', 'message': f"Stream '{net_name}' stopped"})
            else:
                return jsonify({'error': f"No active stream for '{net_name}'", 'status': 'error'}), 404
        except Exception as e:
            logger.exception('Failed to stop webcam stream for %s', net_name)
            return jsonify({'error': str(e), 'status': 'error'}), 500
