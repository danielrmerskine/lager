# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
from flask import Blueprint, render_template, abort

from box_manager import get_box_manager
from nets_reader import read_nets, group_nets_by_instrument

bp = Blueprint('box_detail', __name__)


@bp.route('/box/<box_id>')
def detail(box_id):
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        abort(404)

    status = manager.check_status(box_id)
    nets = read_nets(box_id)
    grouped = group_nets_by_instrument(nets)

    return render_template(
        'box_detail.html',
        box_id=box_id,
        box=box,
        status=status,
        grouped_nets=grouped,
        total_nets=len(nets),
    )
