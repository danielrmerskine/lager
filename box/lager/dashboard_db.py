# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Box-side SQLite database for Lager Dashboard data.

Each box stores its own dashboard data (lines, stations, scripts, runs)
in /etc/lager/dashboard/dashboard.db.  This module uses plain sqlite3 with
no Flask dependency -- it runs on the box, not in the webapp.
"""

import json
import os
import sqlite3
import threading

DB_DIR = '/etc/lager/dashboard'
DB_NAME = 'dashboard.db'

SCHEMA = """\
CREATE TABLE IF NOT EXISTS lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    source_type TEXT DEFAULT 'upload',
    git_repo    TEXT DEFAULT '',
    git_ref     TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id     INTEGER NOT NULL REFERENCES lines(id),
    name        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    password_hash TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS station_scripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    filename    TEXT NOT NULL,
    content     BLOB NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS station_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    status      TEXT NOT NULL DEFAULT 'running',
    event_log   TEXT DEFAULT '[]',
    stdout      TEXT DEFAULT '',
    stderr      TEXT DEFAULT '',
    success     INTEGER DEFAULT 0,
    failure     INTEGER DEFAULT 0,
    failed_step TEXT DEFAULT '',
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    stopped_at  TEXT DEFAULT NULL,
    duration    REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_station_runs_station ON station_runs(station_id);
CREATE INDEX IF NOT EXISTS idx_station_runs_time ON station_runs(started_at);
"""

_local = threading.local()


def _get_db_path():
    return os.path.join(DB_DIR, DB_NAME)


def get_db():
    """Get a thread-local database connection."""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        _local.conn = conn
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

def create_line(name, description='', source_type='upload',
                git_repo='', git_ref=''):
    db = get_db()
    cur = db.execute(
        """INSERT INTO lines (name, description, source_type, git_repo, git_ref)
           VALUES (?, ?, ?, ?, ?)""",
        (name, description, source_type, git_repo, git_ref),
    )
    db.commit()
    return cur.lastrowid


def get_line(line_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM lines WHERE id = ? AND is_deleted = 0', (line_id,)
    ).fetchone()
    return dict(row) if row else None


def list_lines():
    db = get_db()
    rows = db.execute(
        'SELECT * FROM lines WHERE is_deleted = 0 ORDER BY created_at DESC'
    ).fetchall()
    return [dict(r) for r in rows]


def update_line(line_id, **kwargs):
    allowed = {'name', 'description', 'source_type', 'git_repo', 'git_ref'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_parts = []
    values = []
    for k, v in fields.items():
        set_parts.append(f'{k} = ?')
        values.append(v)
    set_parts.append('updated_at = datetime("now")')
    values.append(line_id)
    db = get_db()
    db.execute(
        f'UPDATE lines SET {", ".join(set_parts)} WHERE id = ?', values
    )
    db.commit()


def delete_line(line_id):
    db = get_db()
    db.execute(
        'UPDATE lines SET is_deleted = 1, updated_at = datetime("now") '
        'WHERE id = ?',
        (line_id,),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------

def create_station(line_id, name, source='', password_hash=''):
    db = get_db()
    cur = db.execute(
        """INSERT INTO stations (line_id, name, source, password_hash)
           VALUES (?, ?, ?, ?)""",
        (line_id, name, source, password_hash),
    )
    db.commit()
    return cur.lastrowid


def get_station(station_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM stations WHERE id = ? AND is_deleted = 0',
        (station_id,),
    ).fetchone()
    return dict(row) if row else None


def list_stations(line_id):
    db = get_db()
    rows = db.execute(
        'SELECT * FROM stations WHERE line_id = ? AND is_deleted = 0 '
        'ORDER BY created_at ASC',
        (line_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_station(station_id, **kwargs):
    allowed = {'name', 'source', 'password_hash'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_parts = []
    values = []
    for k, v in fields.items():
        set_parts.append(f'{k} = ?')
        values.append(v)
    set_parts.append('updated_at = datetime("now")')
    values.append(station_id)
    db = get_db()
    db.execute(
        f'UPDATE stations SET {", ".join(set_parts)} WHERE id = ?', values
    )
    db.commit()


def delete_station(station_id):
    db = get_db()
    db.execute(
        'UPDATE stations SET is_deleted = 1, updated_at = datetime("now") '
        'WHERE id = ?',
        (station_id,),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Station Scripts
# ---------------------------------------------------------------------------

def add_station_script(station_id, filename, content, position=None):
    db = get_db()
    if position is None:
        row = db.execute(
            'SELECT COALESCE(MAX(position), -1) + 1 AS next_pos '
            'FROM station_scripts WHERE station_id = ?',
            (station_id,),
        ).fetchone()
        position = row['next_pos']
    cur = db.execute(
        """INSERT INTO station_scripts (station_id, filename, content, position)
           VALUES (?, ?, ?, ?)""",
        (station_id, filename, content, position),
    )
    db.commit()
    return cur.lastrowid


def list_station_scripts(station_id):
    db = get_db()
    rows = db.execute(
        'SELECT * FROM station_scripts WHERE station_id = ? '
        'ORDER BY position ASC',
        (station_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Return content as base64 string for JSON serialization
        if isinstance(d['content'], bytes):
            import base64
            d['content_b64'] = base64.b64encode(d['content']).decode('ascii')
        else:
            d['content_b64'] = d['content']
        result.append(d)
    return result


def get_station_script(script_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM station_scripts WHERE id = ?', (script_id,)
    ).fetchone()
    return dict(row) if row else None


def remove_station_script(script_id):
    db = get_db()
    db.execute('DELETE FROM station_scripts WHERE id = ?', (script_id,))
    db.commit()


def reorder_station_scripts(station_id, script_ids):
    db = get_db()
    for pos, sid in enumerate(script_ids):
        db.execute(
            'UPDATE station_scripts SET position = ? '
            'WHERE id = ? AND station_id = ?',
            (pos, sid, station_id),
        )
    db.commit()


# ---------------------------------------------------------------------------
# Station Runs
# ---------------------------------------------------------------------------

def create_station_run(station_id):
    db = get_db()
    cur = db.execute(
        'INSERT INTO station_runs (station_id) VALUES (?)',
        (station_id,),
    )
    db.commit()
    return cur.lastrowid


def get_station_run(run_id):
    db = get_db()
    row = db.execute(
        'SELECT * FROM station_runs WHERE id = ?', (run_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d['event_log'] = json.loads(d['event_log']) if d['event_log'] else []
    return d


def list_station_runs(station_id=None, line_id=None, limit=100):
    db = get_db()
    query = (
        'SELECT sr.*, s.name AS station_name, l.name AS line_name'
        ' FROM station_runs sr'
        ' JOIN stations s ON sr.station_id = s.id'
        ' JOIN lines l ON s.line_id = l.id'
    )
    params = []
    conditions = []

    if line_id is not None:
        conditions.append('s.line_id = ?')
        params.append(line_id)

    if station_id is not None:
        conditions.append('sr.station_id = ?')
        params.append(station_id)

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    query += ' ORDER BY sr.started_at DESC LIMIT ?'
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['event_log'] = json.loads(d['event_log']) if d['event_log'] else []
        result.append(d)
    return result


def update_station_run(run_id, **kwargs):
    allowed = {'status', 'event_log', 'stdout', 'stderr', 'success',
               'failure', 'failed_step', 'stopped_at', 'duration'}
    fields = {}
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == 'event_log' and not isinstance(v, str):
            v = json.dumps(v)
        fields[k] = v
    if not fields:
        return
    set_parts = []
    values = []
    for k, v in fields.items():
        set_parts.append(f'{k} = ?')
        values.append(v)
    values.append(run_id)
    db = get_db()
    db.execute(
        f'UPDATE station_runs SET {", ".join(set_parts)} WHERE id = ?', values
    )
    db.commit()
