# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared helper functions for dispatcher modules.

These standalone functions provide common functionality used across
multiple dispatcher modules without requiring the full BaseDispatcher class.
They accept an error_class parameter for consistent error handling.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Type

from lager.cache import get_nets_cache


def find_saved_net(
    netname: str, error_class: Type[Exception]
) -> Dict[str, Any]:
    """
    Find a saved net by name.

    Uses the NetsCache for O(1) lookup.

    Args:
        netname: The name of the net to find.
        error_class: The exception class to raise on error.

    Returns:
        The net configuration dictionary.

    Raises:
        error_class: If the net is not found.
    """
    net = get_nets_cache().find_by_name(netname)
    if not net:
        raise error_class(
            f"Net '{netname}' not found. Create it with 'lager nets create'."
        )
    return net


def ensure_role(
    rec: Dict[str, Any],
    expected_role: str,
    error_class: Type[Exception],
) -> None:
    """
    Ensure that a net record has the expected role.

    Args:
        rec: The net configuration record.
        expected_role: The role the net should have.
        error_class: The exception class to raise on error.

    Raises:
        error_class: If the net has a different role.
    """
    actual_role = rec.get("role")
    if actual_role != expected_role:
        netname = rec.get("name", "<unknown>")
        raise error_class(
            f"Net '{netname}' is a '{actual_role}' net, not '{expected_role}'."
        )


def _find_mapping_for_net(
    rec: Dict[str, Any], netname: str
) -> Optional[Dict[str, Any]]:
    """
    Find the mapping entry for a specific net name.

    Args:
        rec: The net configuration record.
        netname: The net name to find mapping for.

    Returns:
        The mapping dictionary if found, None otherwise.
    """
    for m in rec.get("mappings") or []:
        if m.get("net") == netname:
            return m
    return None


def resolve_channel(
    rec: Dict[str, Any],
    netname: str,
    error_class: Type[Exception],
) -> int:
    """
    Resolve the channel/pin number for the net.

    Prefers mappings[].pin that matches this net; else falls back to
    top-level pin.

    Args:
        rec: The net configuration record.
        netname: The net name to resolve channel for.
        error_class: The exception class to raise on error.

    Returns:
        The channel number as an integer.

    Raises:
        error_class: If the channel cannot be resolved.
    """
    mapping = _find_mapping_for_net(rec, netname)
    pin = (mapping or {}).get("pin", rec.get("pin"))
    try:
        return int(pin)
    except (TypeError, ValueError):
        raise error_class(f"Invalid channel pin '{pin}' for net '{netname}'.")


def resolve_address(
    rec: Dict[str, Any],
    netname: str,
    error_class: Type[Exception],
) -> str:
    """
    Resolve the VISA/device address for the net.

    Prefers mappings[].device_override for this net if present;
    else uses rec['address'].

    Args:
        rec: The net configuration record.
        netname: The net name to resolve address for.
        error_class: The exception class to raise on error.

    Returns:
        The device address string.

    Raises:
        error_class: If no address is configured.
    """
    mapping = _find_mapping_for_net(rec, netname)
    addr = (mapping or {}).get("device_override") or rec.get("address")
    if not addr:
        raise error_class(f"Net '{rec.get('name')}' has no VISA address.")
    return addr
