# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
    Box storage utilities for managing local box configurations
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional

from .sort_utils import natural_sort_key


def get_lager_file_path() -> Path:
    """Get the path to the .lager file in home directory."""
    # Check for environment variable override
    if lager_config := os.getenv('LAGER_CONFIG_FILE_DIR'):
        return Path(lager_config) / '.lager'

    # Always use global config in home directory
    return Path.home() / '.lager'


def load_boxes() -> Dict[str, any]:
    """Load boxes from the .lager file.

    Returns a dict where values can be either:
    - str: IP address (legacy format)
    - dict: {"ip": str, "user": str} (new format)
    """
    lager_file = get_lager_file_path()
    if not lager_file.exists():
        return {}

    try:
        with open(lager_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Check for new BOXES key, fallback to DUTS (backward compat), then legacy 'duts'
            return data.get('BOXES') or data.get('DUTS') or data.get('duts', {})
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_boxes(boxes: Dict[str, str]) -> None:
    """Save boxes to the .lager file, preserving all existing data."""
    lager_file = get_lager_file_path()

    # Load existing data or create new structure
    data = {}
    if lager_file.exists():
        try:
            with open(lager_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    data = {}
                elif content[0] in ('{', '['):
                    # JSON format - migrate legacy keys to new format
                    data = json.loads(content)
                    # Migrate legacy lowercase keys to uppercase
                    if 'duts' in data:
                        # Migrate legacy 'duts' to 'BOXES'
                        data['BOXES'] = data.pop('duts')
                    if 'DUTS' in data:
                        # Migrate 'DUTS' to 'BOXES'
                        data['BOXES'] = data.pop('DUTS')
                    if 'nets' in data:
                        data['NETS'] = data.pop('nets')
                    if 'devenv' in data:
                        data['DEVENV'] = data.pop('devenv')
                    if 'LAGER' in data:
                        data['DEFAULTS'] = data.pop('LAGER')
                else:
                    # INI format - convert to JSON preserving all sections
                    from .config import read_config_file, _configparser_to_json
                    config = read_config_file(str(lager_file))
                    data = _configparser_to_json(config)
        except (json.JSONDecodeError, Exception):
            # If we can't parse it, start fresh
            data = {}

    # Use new BOXES key
    data['BOXES'] = boxes

    with open(lager_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def add_box(name: str, ip: str, user: Optional[str] = None, version: Optional[str] = None) -> None:
    """Add a box to the local storage.

    Args:
        name: Box name
        ip: IP address
        user: Optional username (if None and version is None, stores in legacy format)
        version: Optional version/branch name (e.g., "staging", "main")
    """
    boxes = load_boxes()
    if user or version:
        # New format with user and/or version
        box_dict = {"ip": ip}
        if user:
            box_dict["user"] = user
        if version:
            box_dict["version"] = version
        boxes[name] = box_dict
    else:
        # Legacy format (just IP string)
        boxes[name] = ip
    save_boxes(boxes)


def get_box_ip(name: str) -> Optional[str]:
    """Get the IP address for a named box."""
    boxes = load_boxes()
    box_info = boxes.get(name)
    if isinstance(box_info, dict):
        # Dict format: extract IP
        return box_info.get("ip")
    elif isinstance(box_info, str):
        # Legacy format: just the IP
        return box_info
    return None


def get_box_user(name: str) -> Optional[str]:
    """Get the username for a named box.

    Args:
        name: Box name

    Returns:
        Username if stored, None otherwise (will use default)
    """
    boxes = load_boxes()
    box_info = boxes.get(name)
    if isinstance(box_info, dict):
        return box_info.get("user")
    # Legacy format (string IP) has no username
    return None


def get_box_version(name: str) -> Optional[str]:
    """Get the version for a named box.

    Args:
        name: Box name

    Returns:
        Version if stored, None otherwise
    """
    boxes = load_boxes()
    box_info = boxes.get(name)
    if isinstance(box_info, dict):
        return box_info.get("version")
    # Legacy format (string IP) has no version
    return None


def update_box_version(name: str, version: str) -> bool:
    """Update the version for a named box.

    Args:
        name: Box name
        version: Version/branch name (e.g., "staging", "main")

    Returns:
        True if updated, False if box not found
    """
    boxes = load_boxes()
    if name not in boxes:
        return False

    box_info = boxes[name]
    if isinstance(box_info, dict):
        # Update version in existing dict
        box_info["version"] = version
    else:
        # Upgrade from legacy format to dict format
        boxes[name] = {"ip": box_info, "version": version}

    save_boxes(boxes)
    return True


def get_box_name_by_ip(ip: str) -> Optional[str]:
    """Reverse lookup: find box name by IP address.

    Args:
        ip: IP address to lookup

    Returns:
        Box name if found, None otherwise
    """
    boxes = load_boxes()
    for name, box_info in boxes.items():
        box_ip = None
        if isinstance(box_info, dict):
            box_ip = box_info.get("ip")
        elif isinstance(box_info, str):
            box_ip = box_info

        if box_ip == ip:
            return name
    return None


def delete_box(name: str) -> bool:
    """Delete a box from the local storage. Returns True if deleted, False if not found."""
    boxes = load_boxes()
    if name in boxes:
        del boxes[name]
        save_boxes(boxes)
        return True
    return False


def list_boxes() -> Dict[str, str]:
    """List all stored boxes."""
    return load_boxes()


def delete_all_boxes() -> int:
    """Delete all boxes from the local storage. Returns the number of boxes deleted."""
    boxes = load_boxes()
    count = len(boxes)
    save_boxes({})
    return count


def resolve_and_validate_box_with_name(ctx, box_name: Optional[str] = None) -> tuple:
    """
    Resolve and validate a box name, returning both IP and name.

    Args:
        ctx: Click context
        box_name: Box name to resolve (if None, uses default box)

    Returns:
        Tuple of (resolved_ip_or_box_id, original_box_name_or_None)

    Exits with error if box is invalid or not found.
    """
    import click
    import ipaddress
    import os
    from .context import get_default_box

    # If no box name provided, use default box
    if not box_name:
        # Get the default box name before resolving to IP
        default_name = os.getenv('LAGER_BOX') or getattr(ctx.obj, 'default_box', None)
        resolved_ip = get_default_box(ctx)
        return (resolved_ip, default_name)

    # Check if it's a saved box name
    saved_ip = get_box_ip(box_name)
    if saved_ip:
        return (saved_ip, box_name)

    # Check if it's a valid IP address
    try:
        ipaddress.ip_address(box_name)
        return (box_name, None)  # Direct IP, no box name
    except ValueError:
        # Not a valid IP and not in local boxes - Show helpful error
        click.secho(f"Error: Box '{box_name}' not found.", fg='red', err=True)
        click.echo("", err=True)

        saved_boxes = list_boxes()
        if saved_boxes:
            click.echo("Available boxes:", err=True)
            for name, box_info in sorted(saved_boxes.items(), key=lambda x: natural_sort_key(x[0])):
                if isinstance(box_info, dict):
                    box_ip = box_info.get('ip', 'unknown')
                else:
                    box_ip = box_info
                click.echo(f"  - {name} ({box_ip})", err=True)
        else:
            click.echo("No boxes are currently saved.", err=True)

        click.echo("", err=True)
        click.echo("To add a new box, use:", err=True)
        click.echo(f"  lager boxes add --name {box_name} --ip <IP_ADDRESS>", err=True)
        ctx.exit(1)


def resolve_and_validate_box(ctx, box_name: Optional[str] = None) -> str:
    """
    Resolve and validate a box name.

    Args:
        ctx: Click context
        box_name: Box name to resolve (if None, uses default box)

    Returns:
        Resolved box IP address or box ID

    Exits with error if box is invalid or not found.
    """
    import click
    import ipaddress
    from .context import get_default_box

    # If no box name provided, use default box
    if not box_name:
        return get_default_box(ctx)

    # Check if it's a saved box name
    saved_ip = get_box_ip(box_name)
    if saved_ip:
        return saved_ip

    # Check if it's a valid IP address
    try:
        ipaddress.ip_address(box_name)
        return box_name
    except ValueError:
        # Not a valid IP and not in local boxes - Show helpful error
        click.secho(f"Error: Box '{box_name}' not found.", fg='red', err=True)
        click.echo("", err=True)

        saved_boxes = list_boxes()
        if saved_boxes:
            click.echo("Available boxes:", err=True)
            for name, box_info in sorted(saved_boxes.items(), key=lambda x: natural_sort_key(x[0])):
                if isinstance(box_info, dict):
                    box_ip = box_info.get('ip', 'unknown')
                else:
                    box_ip = box_info
                click.echo(f"  - {name} ({box_ip})", err=True)
        else:
            click.echo("No boxes are currently saved.", err=True)

        click.echo("", err=True)
        click.echo("To add a new box, use:", err=True)
        click.echo(f"  lager boxes add --name {box_name} --ip <IP_ADDRESS>", err=True)
        ctx.exit(1)
