# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
import importlib.util
import io
import json
import os
import re

import requests

from box_manager import get_box_manager, BOX_HTTP_PORT, _iter_v1_stream, \
    _LIST_NETS_SCRIPT

# Import NetsCache from lager-factory/lager/nets_cache.py without polluting sys.path
_FACTORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NETS_CACHE_PATH = os.path.join(_FACTORY_ROOT, 'lager', 'nets_cache.py')
_spec = importlib.util.spec_from_file_location('lager_nets_cache', _NETS_CACHE_PATH)
_nets_cache_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_nets_cache_mod)
NetsCache = _nets_cache_mod.NetsCache


def read_nets_local():
    """Read nets from the local saved_nets.json via NetsCache."""
    cache = NetsCache.instance()
    return cache.get_nets()


def read_nets_remote(box_id):
    """Read nets from a remote box via HTTP POST /python endpoint."""
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        return []

    ip = box['ip']
    url = f'http://{ip}:{BOX_HTTP_PORT}/python'

    try:
        script_file = io.BytesIO(_LIST_NETS_SCRIPT)
        files = [
            ('script', ('list_nets.py', script_file, 'application/octet-stream')),
        ]
        resp = requests.post(
            url, files=files, stream=True,
            timeout=(5, 15),
            headers={'Connection': 'close'},
        )
        resp.raise_for_status()

        stdout_bytes = b''
        for fileno, data in _iter_v1_stream(resp):
            if fileno == 1:  # stdout
                stdout_bytes += data

        raw = stdout_bytes.decode('utf-8', errors='replace').strip()
        if not raw:
            return []
        return json.loads(raw)
    except Exception:
        return []


def read_nets(box_id):
    """Read nets for a box. Uses local NetsCache if box is local, otherwise HTTP."""
    manager = get_box_manager()
    box = manager.get_box(box_id)
    if not box:
        return []

    if box.get('local'):
        return read_nets_local()
    return read_nets_remote(box_id)


def group_nets_by_role(nets):
    """Group a list of net dicts by their 'role' field.

    Returns an ordered dict: role -> list of nets.
    Roles with many nets (like 'gpio') are sorted to the end.
    """
    groups = {}
    for net in nets:
        role = net.get('role', 'unknown')
        groups.setdefault(role, []).append(net)

    # Sort: roles with fewer nets first (instruments), many-net roles (gpio) last
    sorted_roles = sorted(groups.keys(), key=lambda r: (len(groups[r]), r))
    return {role: groups[role] for role in sorted_roles}


def _natural_sort_key(s):
    """Sort key that handles embedded numbers naturally (e.g. 'ch2' before 'ch10')."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r'(\d+)', str(s))
    ]


def group_nets_by_instrument(nets):
    """Group a list of net dicts by instrument|address, matching CLI output.

    Returns an ordered dict of (instrument_name, address_label) -> sorted nets.
    """
    by_instrument = {}
    for net in nets:
        instrument = net.get('instrument', '') or ''
        address = net.get('address', '') or ''
        key = f"{instrument}|{address}"
        by_instrument.setdefault(key, []).append(net)

    result = {}
    for key in sorted(by_instrument.keys(), key=_natural_sort_key):
        instrument, addr = key.split('|', 1)
        display_name = instrument.replace('_', ' ')
        if addr and addr != 'NA':
            addr_display = addr if len(addr) <= 50 else addr[:45] + '...'
            group_key = (display_name, f'[{addr_display}]')
        else:
            group_key = (display_name, '')

        sorted_nets = sorted(
            by_instrument[key],
            key=lambda r: (r.get('role', ''), _natural_sort_key(r.get('name', ''))),
        )
        result[group_key] = sorted_nets

    return result
