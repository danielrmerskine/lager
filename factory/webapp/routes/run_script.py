# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
from flask import Blueprint, render_template, request

from box_manager import get_box_manager

bp = Blueprint('run_script', __name__)


@bp.route('/run')
def run_page():
    manager = get_box_manager()
    boxes = manager.boxes
    selected_box = request.args.get('box', '')
    return render_template('run_script.html', boxes=boxes, selected_box=selected_box)
