# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for factory webapp tests.

Adds factory/webapp/ to sys.path so bare imports (``import script_runner``,
``import box_manager``, etc.) resolve correctly, and patches out the lager
config loader so we don't need the real factory/lager/ tree.
"""

import json
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# 1. Put factory/webapp/ on sys.path so the app's bare imports work.
# ---------------------------------------------------------------------------
_WEBAPP_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, 'factory', 'webapp',
)
_WEBAPP_DIR = os.path.normpath(_WEBAPP_DIR)
if _WEBAPP_DIR not in sys.path:
    sys.path.insert(0, _WEBAPP_DIR)


# ---------------------------------------------------------------------------
# 2. Patch config.load_lager_config BEFORE anything imports config.py,
#    so it never tries to load factory/lager/config.py.
# ---------------------------------------------------------------------------
TEST_BOXES = {
    'test-box': {
        'ip': '192.0.2.1',
        'ssh_user': 'lager',
        'container': 'lager',
    },
    'test-box-2': {
        'ip': '192.0.2.2',
        'ssh_user': 'lager',
        'container': 'lager',
    },
}


def _fake_load_lager_config():
    return {'BOXES': TEST_BOXES}


# Patch before any webapp code can be imported
import importlib
import importlib.util

# Create a shim config module that doesn't touch the real lager config tree
_config_path = os.path.join(_WEBAPP_DIR, 'config.py')

# We need to intercept the lager_config_mod loading inside config.py
# Do this by pre-creating a fake module
import types
_fake_lager_config = types.ModuleType('lager_config')
_fake_lager_config.load_config = _fake_load_lager_config
sys.modules['lager_config'] = _fake_lager_config

# Now patch importlib.util so config.py's dynamic import returns our fake
_orig_spec_from_file = importlib.util.spec_from_file_location


class _FakeLagerConfigLoader:
    """Fake loader that injects load_config into the module."""
    def create_module(self, spec):
        return None  # Use default module creation semantics
    def exec_module(self, module):
        module.load_config = _fake_load_lager_config

def _patched_spec_from_file(name, location, *args, **kwargs):
    if name == 'lager_config':
        spec = importlib.machinery.ModuleSpec(name, _FakeLagerConfigLoader())
        return spec
    return _orig_spec_from_file(name, location, *args, **kwargs)


importlib.util.spec_from_file_location = _patched_spec_from_file

# Patch exec_module to be a no-op for our fake module
_orig_exec_module = None

# Simpler: just set the module-level variables that config.py creates
# by pre-loading config.py with our patches
import unittest.mock as _mock

_config_patcher = _mock.patch.dict('os.environ', {}, clear=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Set LAGER_WEBAPP_DATA_DIR to a temp directory and create subdirs."""
    data_dir = str(tmp_path / 'data')
    os.makedirs(os.path.join(data_dir, 'scripts'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'history'), exist_ok=True)

    old_val = os.environ.get('LAGER_WEBAPP_DATA_DIR')
    os.environ['LAGER_WEBAPP_DATA_DIR'] = data_dir
    yield data_dir
    if old_val is None:
        os.environ.pop('LAGER_WEBAPP_DATA_DIR', None)
    else:
        os.environ['LAGER_WEBAPP_DATA_DIR'] = old_val


@pytest.fixture()
def app(tmp_data_dir, monkeypatch):
    """Create a Flask app for testing."""
    # Reset box_manager singleton between tests
    import box_manager as bm_mod
    monkeypatch.setattr(bm_mod, '_manager', None)

    # Reset script_store's _DATA_DIR to use tmp_data_dir
    import script_store
    monkeypatch.setattr(
        script_store, '_DATA_DIR',
        os.path.join(tmp_data_dir, 'scripts'),
    )

    from app import create_app
    application = create_app({'TESTING': True})

    yield application


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture()
def mock_box_manager(monkeypatch):
    """Patch box_manager singleton with TEST_BOXES."""
    import box_manager as bm_mod
    manager = bm_mod.BoxManager(boxes=TEST_BOXES)
    monkeypatch.setattr(bm_mod, '_manager', manager)
    return manager
