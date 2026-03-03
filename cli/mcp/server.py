#!/usr/bin/env python3
# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
Lager MCP Server - Model Context Protocol server for Lager hardware boxes.

Lets AI assistants (Claude Code, Cursor, VS Code Copilot) interact with
Lager boxes directly: scanning I2C buses, reading sensors, configuring
power supplies, etc.

Architecture:
    AI Tool (Claude Code/Cursor)
        |  stdio (JSON-RPC)
        v
    Lager MCP Server (this process, runs on developer machine)
        |  subprocess calls to `lager` CLI
        v
    Lager Box (existing box_http_server.py)

Usage:
    # Run directly (requires pip install lager-cli[mcp])
    lager-mcp

    # Add to Claude Code
    claude mcp add --transport stdio lager -- lager-mcp

    # Alternative: run as a Python module
    python -m cli.mcp

    # Test with MCP inspector
    mcp dev cli/mcp/server.py
"""

import subprocess

from mcp.server.fastmcp import FastMCP

# Create the MCP server instance
mcp = FastMCP(
    "lager",
    instructions="Control Lager hardware boxes from AI assistants. "
    "Interact with I2C, SPI, power supplies, ADC/DAC, and GPIO.",
)


def run_lager(*args: str, timeout: int = 60) -> str:
    """Run a lager CLI command and return output.

    Args:
        *args: Command-line arguments passed to the `lager` binary.
        timeout: Maximum seconds to wait for the command to complete.

    Returns:
        stdout on success, or an error message on failure.
    """
    try:
        result = subprocess.run(
            ["lager"] + list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return (
            "Error: 'lager' CLI not found. "
            "Install with: cd cli && pip install -e ."
        )
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"

    output = result.stdout.strip()
    errors = result.stderr.strip()

    if result.returncode != 0:
        # Combine stdout and stderr for error context
        parts = []
        if output:
            parts.append(output)
        if errors:
            parts.append(errors)
        return f"Error (exit {result.returncode}): {' | '.join(parts) or 'unknown error'}"

    # Include any stderr warnings alongside stdout
    if errors and output:
        return f"{output}\n\n[warnings] {errors}"
    return output or "(no output)"


# ---------------------------------------------------------------------------
# Register tools from submodules
# ---------------------------------------------------------------------------
# Each submodule calls `mcp.tool()` to register its tools when imported.
# Import order doesn't matter; all tools are registered before `mcp.run()`.
from .tools import box  # noqa: E402, F401
from .tools import i2c  # noqa: E402, F401
from .tools import spi  # noqa: E402, F401
from .tools import power  # noqa: E402, F401
from .tools import measurement  # noqa: E402, F401
from .tools import battery  # noqa: E402, F401
from .tools import eload  # noqa: E402, F401
from .tools import uart  # noqa: E402, F401
from .tools import usb  # noqa: E402, F401
from .tools import ble  # noqa: E402, F401
from .tools import blufi  # noqa: E402, F401
from .tools import debug  # noqa: E402, F401
from .tools import scope  # noqa: E402, F401
from .tools import logic  # noqa: E402, F401
from .tools import webcam  # noqa: E402, F401
from .tools import defaults  # noqa: E402, F401
from .tools import solar  # noqa: E402, F401
from .tools import wifi  # noqa: E402, F401
from .tools import arm  # noqa: E402, F401
from .tools import python_run  # noqa: E402, F401
from .tools import pip_tools  # noqa: E402, F401
from .tools import logs  # noqa: E402, F401
from .tools import binaries  # noqa: E402, F401


def main():
    """Entry point for the Lager MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
