# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
import json
import os

_LAGER_CONFIG_FILENAME = '.lager'


def get_config_path():
    """Return the path to the .lager config file.

    Checks LAGER_CONFIG_FILE_DIR env var first, falls back to ~/.lager.
    """
    config_dir = os.getenv('LAGER_CONFIG_FILE_DIR', os.path.expanduser('~'))
    return os.path.join(config_dir, _LAGER_CONFIG_FILENAME)


def load_config():
    """Load and return the .lager config as a dict. Returns {} if not found."""
    path = get_config_path()
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)
