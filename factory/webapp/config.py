# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
import os

# Import lager-factory/lager/config.py without name collision (this file is also config.py)
_FACTORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAGER_CONFIG_PATH = os.path.join(_FACTORY_ROOT, 'lager', 'config.py')
_spec = importlib.util.spec_from_file_location('lager_config', _LAGER_CONFIG_PATH)
_lager_config_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lager_config_mod)
load_lager_config = _lager_config_mod.load_config


def load_boxes():
    """Load the box list from .lager config or standalone JSON file.

    Checks the .lager config BOXES section first. Falls back to a standalone
    JSON file specified by LAGER_WEBAPP_BOXES_FILE env var.

    Returns a dict of box_id -> box config dict. Each box config has:
        name, ip, ssh_user, container, layout (optional)
    """
    lager_config = load_lager_config()
    boxes = lager_config.get('BOXES')
    if boxes:
        result = {}
        for k, v in boxes.items():
            if isinstance(v, dict):
                result[k] = v
            elif isinstance(v, str):
                # Legacy format: box value is just an IP string
                result[k] = {'ip': v}
        return result

    boxes_file = os.getenv('LAGER_WEBAPP_BOXES_FILE')
    if boxes_file and os.path.exists(boxes_file):
        with open(boxes_file) as f:
            return json.load(f)

    return {}


class Config:
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
    BOXES = load_boxes()


if Config.SECRET_KEY == 'dev-secret-key-change-in-production':
    import sys as _sys
    print(
        'WARNING: Using default SECRET_KEY. Set FLASK_SECRET_KEY '
        'environment variable for production use.',
        file=_sys.stderr,
    )
