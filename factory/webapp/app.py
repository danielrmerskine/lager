# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
from flask import Flask

from config import Config


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    from routes.dashboard import bp as dashboard_bp
    from routes.box_detail import bp as box_detail_bp
    from routes.run_script import bp as run_script_bp
    from routes.results import bp as results_bp
    from routes.api import bp as api_bp
    from routes.webcam import bp as webcam_bp
    from routes.box_lines import bp as box_lines_bp
    from routes.box_stations import bp as box_stations_bp
    from routes.box_station_runner import bp as box_station_runner_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(box_detail_bp)
    app.register_blueprint(run_script_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(webcam_bp)
    app.register_blueprint(box_lines_bp)
    app.register_blueprint(box_stations_bp)
    app.register_blueprint(box_station_runner_bp)

    # Initialize flask-sock for WebSocket support
    from flask_sock import Sock
    sock = Sock(app)
    app.sock = sock

    # Register WebSocket routes
    from routes.box_station_runner import register_ws_routes
    register_ws_routes(sock)

    return app
