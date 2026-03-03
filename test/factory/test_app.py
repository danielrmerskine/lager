# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/app.py.

Covers create_app (Flask instance, blueprints, custom config).
"""

import os

import pytest

from app import create_app


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------

class TestCreateApp:

    def test_returns_flask_instance(self, app):
        """create_app returns a Flask application instance."""
        from flask import Flask
        assert isinstance(app, Flask)

    def test_registers_all_blueprints(self, app):
        """create_app registers the 9 expected blueprints."""
        expected_blueprints = {
            'dashboard',
            'box_detail',
            'run_script',
            'results',
            'api',
            'webcam',
            'box_lines',
            'box_stations',
            'box_station_runner',
        }
        registered = set(app.blueprints.keys())
        assert expected_blueprints.issubset(registered), (
            f"Missing blueprints: {expected_blueprints - registered}"
        )

    def test_custom_config_applied(self, tmp_data_dir):
        """Custom config dict passed to create_app is merged into app.config."""
        application = create_app({'TESTING': True})
        assert application.config['TESTING'] is True
