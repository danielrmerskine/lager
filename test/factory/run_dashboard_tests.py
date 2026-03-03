#!/usr/bin/env python3

# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Automated dashboard production readiness tests (Tier 2 + Tier 3).

Uses Flask test client -- no separate server process needed.
Run from repo root: python test/factory/run_dashboard_tests.py
"""

import io
import os
import re
import sys
import json
import subprocess
import tempfile

# Add webapp directory to sys.path so we can import the app
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          'factory', 'webapp')
sys.path.insert(0, WEBAPP_DIR)

# Use a temp DB so we don't pollute real data
_temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_temp_db.close()
os.environ['FACTORY_DB_PATH'] = _temp_db.name

from app import create_app

results = {}


def record(test_id, description, passed, actual):
    status = 'PASS' if passed else 'FAIL'
    results[test_id] = {
        'description': description,
        'status': status,
        'actual': actual,
    }
    marker = ' OK ' if passed else 'FAIL'
    print(f'[{marker}] {test_id}: {description}')
    if not passed:
        print(f'       Actual: {actual}')


def main():
    app = create_app()
    app.config['TESTING'] = True
    # Disable CSRF / redirect following where needed
    client = app.test_client()

    # ---------------------------------------------------------------
    # Tier 2: Server + HTTP tests
    # ---------------------------------------------------------------

    # 1.4: Default port works (GET / -> 200)
    resp = client.get('/')
    record('1.4', 'Default port works (GET / -> 200)',
           resp.status_code == 200,
           f'status={resp.status_code}')

    # 2.1: Nav active on /
    html = resp.data.decode()
    # The template renders: class="nav-link active" aria-current="page" on the Dashboard link when path == '/'
    dashboard_link_active = 'nav-link active" aria-current="page"\n               href="/">Dashboard' in html or \
                            ('active' in html and 'aria-current="page"' in html and 'href="/">Dashboard' in html)
    # More precise check: find the Dashboard link and verify it has active
    dash_match = re.search(r'<a\s+class="nav-link ([^"]*)"[^>]*href="/">Dashboard</a>', html)
    dash_active = dash_match and 'active' in dash_match.group(1) if dash_match else False
    record('2.1', 'Nav active on /',
           dash_active,
           f'Dashboard link classes: {dash_match.group(1) if dash_match else "NOT FOUND"}')

    # 2.2: Nav active on /lines
    resp_lines = client.get('/lines')
    html_lines = resp_lines.data.decode()
    lines_match = re.search(r'<a\s+class="nav-link ([^"]*)"[^>]*href="/lines">Lines</a>', html_lines)
    lines_active = lines_match and 'active' in lines_match.group(1) if lines_match else False
    # Also check Dashboard is NOT active on /lines
    dash_on_lines = re.search(r'<a\s+class="nav-link ([^"]*)"[^>]*href="/">Dashboard</a>', html_lines)
    dash_not_active = dash_on_lines and 'active' not in dash_on_lines.group(1) if dash_on_lines else False
    record('2.2', 'Nav active on /lines',
           lines_active and dash_not_active,
           f'Lines classes: {lines_match.group(1) if lines_match else "NOT FOUND"}, '
           f'Dashboard classes: {dash_on_lines.group(1) if dash_on_lines else "NOT FOUND"}')

    # 2.3: Nav active on /run
    resp_run = client.get('/run')
    html_run = resp_run.data.decode()
    run_match = re.search(r'<a\s+class="nav-link ([^"]*)"[^>]*href="/run">Run Script</a>', html_run)
    run_active = run_match and 'active' in run_match.group(1) if run_match else False
    record('2.3', 'Nav active on /run',
           run_active,
           f'Run Script classes: {run_match.group(1) if run_match else "NOT FOUND"}')

    # 2.4: Nav active on /results
    resp_results = client.get('/results')
    html_results = resp_results.data.decode()
    results_match = re.search(r'<a\s+class="nav-link ([^"]*)"[^>]*href="/results">Results</a>', html_results)
    results_active = results_match and 'active' in results_match.group(1) if results_match else False
    record('2.4', 'Nav active on /results',
           results_active,
           f'Results classes: {results_match.group(1) if results_match else "NOT FOUND"}')

    # 7.1: Page titles say "Lager Dashboard"
    pages = {
        '/': 'Dashboard',
        '/lines': 'Lines',
        '/run': 'Run Script',
        '/results': 'Results',
    }
    all_titles_ok = True
    title_details = []
    for path, label in pages.items():
        if path == '/':
            page_html = html
        elif path == '/lines':
            page_html = html_lines
        elif path == '/run':
            page_html = html_run
        elif path == '/results':
            page_html = html_results
        title_match = re.search(r'<title>([^<]+)</title>', page_html)
        title_text = title_match.group(1) if title_match else 'NO TITLE'
        has_dashboard = 'Lager Dashboard' in title_text
        has_factory = 'factory' in title_text.lower()
        ok = has_dashboard and not has_factory
        if not ok:
            all_titles_ok = False
        title_details.append(f'{path}: "{title_text}" ({"OK" if ok else "FAIL"})')
    record('7.1', 'Page titles say "Lager Dashboard"',
           all_titles_ok,
           '; '.join(title_details))

    # 7.2: Navbar brand text
    brand_match = re.search(r'<a\s+class="navbar-brand"[^>]*>([^<]+)</a>', html)
    brand_text = brand_match.group(1).strip() if brand_match else 'NOT FOUND'
    record('7.2', 'Navbar brand says "Lager Dashboard"',
           brand_text == 'Lager Dashboard',
           f'Brand text: "{brand_text}"')

    # 8.4: Results page loads (GET /results -> 200)
    record('8.4', 'Results page loads (GET /results -> 200)',
           resp_results.status_code == 200,
           f'status={resp_results.status_code}')

    # 6.2: SECRET_KEY warning
    # Run a subprocess with FLASK_SECRET_KEY unset and capture stderr
    test_script = '''
import os, sys
os.environ.pop('FLASK_SECRET_KEY', None)
sys.path.insert(0, {webapp_dir!r})
# Re-import config to trigger the warning check
import importlib
import config as cfg
importlib.reload(cfg)
'''.format(webapp_dir=WEBAPP_DIR)
    env = dict(os.environ)
    env.pop('FLASK_SECRET_KEY', None)
    env.pop('FACTORY_DB_PATH', None)  # Not needed for this test
    result_62 = subprocess.run(
        [sys.executable, '-c', test_script],
        capture_output=True, text=True, env=env, timeout=10,
    )
    has_warning = 'WARNING: Using default SECRET_KEY' in result_62.stderr
    record('6.2', 'SECRET_KEY warning when env var unset',
           has_warning,
           f'stderr: {result_62.stderr.strip()!r}')

    # 6.2b: SECRET_KEY warning suppressed when set
    env_with_key = dict(os.environ)
    # Intentional test value -- not a real secret
    env_with_key['FLASK_SECRET_KEY'] = 'my-test-secret'
    env_with_key.pop('FACTORY_DB_PATH', None)
    result_62b = subprocess.run(
        [sys.executable, '-c', test_script.replace("os.environ.pop('FLASK_SECRET_KEY', None)", "pass")],
        capture_output=True, text=True, env=env_with_key, timeout=10,
    )
    no_warning = 'WARNING: Using default SECRET_KEY' not in result_62b.stderr
    record('6.2b', 'SECRET_KEY warning suppressed with env var',
           no_warning,
           f'stderr: {result_62b.stderr.strip()!r}')

    # ---------------------------------------------------------------
    # Tier 3: Server + Data Operations
    # ---------------------------------------------------------------

    # We need a box_id that won't cause issues. Use a fake one.
    fake_box = 'TEST-AUTOMATED'

    # Create a test line
    resp_create_line = client.post('/api/lines',
        data=json.dumps({'name': 'AutoTest Line', 'box_id': fake_box}),
        content_type='application/json')
    line_data = resp_create_line.get_json()
    line_id = line_data.get('id') if line_data else None
    line_created = resp_create_line.status_code == 201 and line_id is not None

    # Create a test station under that line
    station_id = None
    if line_id:
        resp_create_station = client.post(f'/api/lines/{line_id}/stations',
            data=json.dumps({'name': 'AutoTest Station'}),
            content_type='application/json')
        station_data = resp_create_station.get_json()
        station_id = station_data.get('id') if station_data else None

    # 6.3a: Path traversal via station upload
    if station_id:
        data_63a = {
            'files': (io.BytesIO(b'print("test")'), '../../../etc/passwd.py'),
        }
        resp_63a = client.post(
            f'/api/stations/{station_id}/scripts/upload',
            data=data_63a,
            content_type='multipart/form-data',
        )
        json_63a = resp_63a.get_json()
        added_63a = json_63a.get('added', []) if json_63a else []
        # Should be sanitized -- no path separators
        sanitized_ok = len(added_63a) == 1 and '/' not in added_63a[0] and '..' not in added_63a[0]
        record('6.3a', 'Path traversal (station upload) sanitized',
               sanitized_ok,
               f'added={added_63a}')
    else:
        record('6.3a', 'Path traversal (station upload) sanitized',
               False, 'Could not create test station')

    # 6.3b: Path traversal via API
    if station_id:
        data_63b = {
            'files': (io.BytesIO(b'print("evil")'), '../../../tmp/evil.py'),
        }
        resp_63b = client.post(
            f'/api/stations/{station_id}/scripts/upload',
            data=data_63b,
            content_type='multipart/form-data',
        )
        json_63b = resp_63b.get_json()
        added_63b = json_63b.get('added', []) if json_63b else []
        sanitized_ok_b = len(added_63b) == 1 and '/' not in added_63b[0] and '..' not in added_63b[0]
        record('6.3b', 'Path traversal (API) sanitized',
               sanitized_ok_b,
               f'added={added_63b}')
    else:
        record('6.3b', 'Path traversal (API) sanitized',
               False, 'Could not create test station')

    # 6.3c: Empty filename rejected
    if station_id:
        data_63c = {
            'files': (io.BytesIO(b'print("empty")'), '.py'),
        }
        resp_63c = client.post(
            f'/api/stations/{station_id}/scripts/upload',
            data=data_63c,
            content_type='multipart/form-data',
        )
        json_63c = resp_63c.get_json()
        added_63c = json_63c.get('added', []) if json_63c else []
        record('6.3c', 'Empty filename (.py) rejected',
               len(added_63c) == 0,
               f'added={added_63c}')
    else:
        record('6.3c', 'Empty filename (.py) rejected',
               False, 'Could not create test station')

    # 6.3d: Normal upload works
    if station_id:
        data_63d = {
            'files': (io.BytesIO(b'print("supply test")'), 'test_supply.py'),
        }
        resp_63d = client.post(
            f'/api/stations/{station_id}/scripts/upload',
            data=data_63d,
            content_type='multipart/form-data',
        )
        json_63d = resp_63d.get_json()
        added_63d = json_63d.get('added', []) if json_63d else []
        record('6.3d', 'Normal upload (test_supply.py) works',
               'test_supply.py' in added_63d,
               f'added={added_63d}')
    else:
        record('6.3d', 'Normal upload (test_supply.py) works',
               False, 'Could not create test station')

    # 3.1: Station detail after parent line deleted
    if line_id and station_id:
        # Delete the line
        client.delete(f'/api/lines/{line_id}')
        # Now try to access the station detail
        resp_31 = client.get(f'/stations/{station_id}')
        # Should redirect (302) to /lines
        is_redirect = resp_31.status_code in (301, 302, 303, 307, 308)
        redirects_to_lines = '/lines' in (resp_31.headers.get('Location', '') or '')
        record('3.1', 'Station detail after parent line deleted -> redirect',
               is_redirect and redirects_to_lines,
               f'status={resp_31.status_code}, Location={resp_31.headers.get("Location", "NONE")}')
    else:
        record('3.1', 'Station detail after parent line deleted -> redirect',
               False, 'Could not create test data')

    # 3.2: Station run page after parent line deleted
    if station_id:
        resp_32 = client.get(f'/stations/{station_id}/run')
        is_redirect = resp_32.status_code in (301, 302, 303, 307, 308)
        redirects_to_lines = '/lines' in (resp_32.headers.get('Location', '') or '')
        record('3.2', 'Station run page after parent line deleted -> redirect',
               is_redirect and redirects_to_lines,
               f'status={resp_32.status_code}, Location={resp_32.headers.get("Location", "NONE")}')
    else:
        record('3.2', 'Station run page after parent line deleted -> redirect',
               False, 'Could not create test data')

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    print('\n' + '=' * 60)
    print('RESULTS SUMMARY')
    print('=' * 60)
    pass_count = sum(1 for r in results.values() if r['status'] == 'PASS')
    fail_count = sum(1 for r in results.values() if r['status'] == 'FAIL')
    total = len(results)
    print(f'Total: {total}  |  Pass: {pass_count}  |  Fail: {fail_count}')
    print()
    for tid, r in sorted(results.items()):
        print(f'  {r["status"]:4s}  {tid}: {r["description"]}')
        if r['status'] == 'FAIL':
            print(f'        -> {r["actual"]}')
    print()

    # Dump results as JSON for the report
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'dashboard_test_results.json')
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'Results saved to {json_path}')

    # Cleanup temp DB
    try:
        os.unlink(_temp_db.name)
    except OSError:
        pass

    return 0 if fail_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
