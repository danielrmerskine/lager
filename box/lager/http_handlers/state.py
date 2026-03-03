# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
Global state management for HTTP/WebSocket sessions.

This module provides thread-safe storage for active sessions across
UART, supply, and battery handlers.
"""
import threading

# Global dictionary to track active UART sessions
# Format: {session_id: {'driver': driver_obj, 'thread': thread_obj, 'stop_event': event_obj}}
active_uart_sessions = {}
active_uart_sessions_lock = threading.Lock()

# Global dictionary to track active supply monitoring sessions
# Format: {session_id: {'netname': str, 'stop_event': event_obj, 'thread': thread_obj, 'instrument_lock': Lock}}
active_supply_sessions = {}
active_supply_sessions_lock = threading.Lock()

# Global dictionary to track active battery monitoring sessions
# Format: {session_id: {'netname': str, 'stop_event': event_obj, 'thread': thread_obj, 'instrument_lock': Lock}}
active_battery_sessions = {}
active_battery_sessions_lock = threading.Lock()

# Global dictionary to track instrument locks (one lock per netname to prevent concurrent SCPI queries)
# Format: {netname: threading.Lock()}
instrument_locks = {}
instrument_locks_lock = threading.Lock()


def get_instrument_lock(netname):
    """Get or create an instrument lock for a given netname."""
    with instrument_locks_lock:
        if netname not in instrument_locks:
            instrument_locks[netname] = threading.Lock()
        return instrument_locks[netname]


def cleanup_all_sessions():
    """Clean up all active sessions. Called during graceful shutdown."""
    # Cleanup UART sessions
    with active_uart_sessions_lock:
        for session_id, session in list(active_uart_sessions.items()):
            try:
                if 'stop_event' in session:
                    session['stop_event'].set()
                if 'driver' in session:
                    session['driver']._cleanup()
            except Exception:
                pass
        active_uart_sessions.clear()

    # Cleanup supply sessions
    with active_supply_sessions_lock:
        for session_id, session in list(active_supply_sessions.items()):
            try:
                if 'stop_event' in session:
                    session['stop_event'].set()
            except Exception:
                pass
        active_supply_sessions.clear()

    # Cleanup battery sessions
    with active_battery_sessions_lock:
        for session_id, session in list(active_battery_sessions.items()):
            try:
                if 'stop_event' in session:
                    session['stop_event'].set()
            except Exception:
                pass
        active_battery_sessions.clear()
