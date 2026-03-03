# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
import json
import os
import threading

SAVED_NETS_PATH = '/etc/lager/saved_nets.json'


class NetsCache:
    """Thread-safe, cached access to saved_nets.json.

    Singleton pattern with double-check locking. Detects file modifications
    via os.path.getmtime() and auto-reloads when the file changes.
    """
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._data_lock = threading.Lock()
        self._nets = []
        self._last_mtime = 0
        self._path = os.getenv('LAGER_SAVED_NETS_PATH', SAVED_NETS_PATH)

    @classmethod
    def instance(cls):
        """Return the singleton NetsCache instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _maybe_reload(self):
        """Reload from file if it has been modified since last read."""
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return
        if mtime != self._last_mtime:
            with open(self._path) as f:
                self._nets = json.load(f)
            self._last_mtime = mtime

    def get_nets(self):
        """Return all nets (reloads from file if modified)."""
        with self._data_lock:
            self._maybe_reload()
            return list(self._nets)
