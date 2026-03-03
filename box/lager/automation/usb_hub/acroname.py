# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
AcronameUSBNet – driver for USBHub2x4 / USBHub3p / USBHub3c.

Implements: enable / disable / toggle
Lazy-imports BrainStem to minimise start-up cost.
"""

from __future__ import annotations

from .usb_net import USBNet, LibraryMissingError, DeviceNotFoundError, PortStateError


class AcronameUSBNet(USBNet):
    """USBNet driver for Acroname STEM hubs (0-based port numbers)."""

    _cached_hub = None  # singleton connection
    _brainstem = None   # cached vendor module
    _Result = None      # brainstem.result.Result alias

    # ------------------------------------------------------------------ #
    # helper: import BrainStem only when needed
    # ------------------------------------------------------------------ #
    def _require_library(self):
        if AcronameUSBNet._brainstem is not None:
            return  # already imported

        try:
            import brainstem  # pylint: disable=import-error
            from brainstem.result import Result
        except ModuleNotFoundError as exc:
            raise LibraryMissingError(
                "BrainStem Python SDK not installed inside the box "
                "(pip install brainstem)."
            ) from exc

        AcronameUSBNet._brainstem = brainstem
        AcronameUSBNet._Result = Result

    # ------------------------------------------------------------------ #
    # lazy hub discovery (singleton)
    # ------------------------------------------------------------------ #
    def _connect_hub(self):
        self._require_library()
        if AcronameUSBNet._cached_hub:
            return AcronameUSBNet._cached_hub

        for cls in (
            self._brainstem.stem.USBHub2x4,
            self._brainstem.stem.USBHub3p,
            self._brainstem.stem.USBHub3c,
        ):
            hub = cls()
            if hub.discoverAndConnect(self._brainstem.link.Spec.USB) == self._Result.NO_ERROR:
                AcronameUSBNet._cached_hub = hub
                return hub

        raise DeviceNotFoundError("No Acroname hub detected on USB")

    # ------------------------------------------------------------------ #
    # constructor (argument ignored, kept for signature compatibility)
    # ------------------------------------------------------------------ #
    def __init__(self, _net_info: dict | None = None) -> None:
        pass

    # ------------------------------------------------------------------ #
    # internal – decode enable+power bits
    # ------------------------------------------------------------------ #
    @staticmethod
    def _port_enabled(raw_state: int) -> bool:
        return (raw_state & 0b11) == 0b11

    # ------------------------------------------------------------------ #
    # USBNet interface
    # ------------------------------------------------------------------ #
    def enable(self, net_name: str, port: int) -> None:  # type: ignore[override]
        hub = self._connect_hub()
        hub.usb.setPortEnable(port)

    def disable(self, net_name: str, port: int) -> None:  # type: ignore[override]
        hub = self._connect_hub()
        hub.usb.setPortDisable(port)

    def toggle(self, net_name: str, port: int) -> None:  # type: ignore[override]
        hub = self._connect_hub()
        res = hub.usb.getPortState(port)
        if res.error != self._Result.NO_ERROR:
            raise PortStateError(f"Acroname error code {res.error}")

        currently_on = self._port_enabled(res.value)
        if currently_on:
            hub.usb.setPortDisable(port)
        else:
            hub.usb.setPortEnable(port)
