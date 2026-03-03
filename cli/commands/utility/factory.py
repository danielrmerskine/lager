# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
lager.commands.utility.factory

Start the Lager Factory webapp.
"""

import os
import socket
import subprocess
import sys

import click


def _get_local_ip():
    """Best-effort detection of the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


@click.command('factory')
@click.option('--port', default=5001, type=int, help='Port number')
@click.option('--host', default='0.0.0.0', help='Host to bind to')
def factory(port, host):
    """Start the Lager Factory."""
    if port < 0 or port > 65535:
        click.secho(f'Error: Port must be between 0 and 65535, got {port}.', fg='red', err=True)
        raise SystemExit(1)

    # Locate webapp directory relative to CLI package
    cli_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    )))
    webapp_dir = os.path.join(os.path.dirname(cli_dir), 'factory', 'webapp')

    if not os.path.isdir(webapp_dir):
        click.secho(
            f'Factory webapp not found at {webapp_dir}', fg='red', err=True
        )
        raise SystemExit(1)

    run_py = os.path.join(webapp_dir, 'run.py')
    if not os.path.isfile(run_py):
        click.secho(
            f'run.py not found at {run_py}', fg='red', err=True
        )
        raise SystemExit(1)

    local_ip = _get_local_ip()
    click.secho('Lager Factory starting...', fg='green')
    click.secho(f'  Local:   http://127.0.0.1:{port}')
    click.secho(f'  Network: http://{local_ip}:{port}')

    env = dict(os.environ, PORT=str(port), HOST=host)

    try:
        subprocess.run(
            [sys.executable, 'run.py'],
            cwd=webapp_dir,
            env=env,
        )
    except KeyboardInterrupt:
        pass
