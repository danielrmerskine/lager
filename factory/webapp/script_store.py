# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Filesystem-backed storage for uploaded test scripts.

Scripts are stored as files in a data directory. Execution order is tracked
in a manifest.json file (a JSON array of filenames).
"""

import json
import os
import threading

_lock = threading.Lock()

_DATA_DIR = os.path.join(
    os.getenv('LAGER_WEBAPP_DATA_DIR', os.path.join(os.path.dirname(__file__), 'data')),
    'scripts',
)


def _ensure_dirs():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _manifest_path():
    return os.path.join(_DATA_DIR, 'manifest.json')


def _load_manifest():
    path = _manifest_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save_manifest(names):
    with open(_manifest_path(), 'w') as f:
        json.dump(names, f, indent=2)


def list_scripts():
    """Return ordered list of dicts: {name, size_bytes}."""
    with _lock:
        _ensure_dirs()
        manifest = _load_manifest()
        result = []
        for name in manifest:
            path = os.path.join(_DATA_DIR, name)
            if os.path.exists(path):
                result.append({
                    'name': name,
                    'size_bytes': os.path.getsize(path),
                })
        return result


def add_script(filename, content_bytes):
    """Store a script file. Re-uploading overwrites content, keeps position."""
    safe_name = os.path.basename(filename)
    if not safe_name.endswith('.py'):
        raise ValueError('Only .py files are allowed')

    with _lock:
        _ensure_dirs()
        path = os.path.join(_DATA_DIR, safe_name)
        with open(path, 'wb') as f:
            f.write(content_bytes)

        manifest = _load_manifest()
        if safe_name not in manifest:
            manifest.append(safe_name)
            _save_manifest(manifest)


def remove_script(filename):
    """Remove a script file and its manifest entry."""
    safe_name = os.path.basename(filename)

    with _lock:
        _ensure_dirs()
        path = os.path.join(_DATA_DIR, safe_name)
        if os.path.exists(path):
            os.remove(path)

        manifest = _load_manifest()
        if safe_name in manifest:
            manifest.remove(safe_name)
            _save_manifest(manifest)


def reorder_scripts(ordered_names):
    """Set the execution order. Names must match existing scripts."""
    with _lock:
        _ensure_dirs()
        manifest = _load_manifest()
        # Validate all names exist
        for name in ordered_names:
            if name not in manifest:
                raise ValueError(f'Unknown script: {name}')
        _save_manifest(list(ordered_names))


def get_script_content(filename):
    """Return script content as string, or None if not found."""
    safe_name = os.path.basename(filename)
    with _lock:
        path = os.path.join(_DATA_DIR, safe_name)
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
    return None
