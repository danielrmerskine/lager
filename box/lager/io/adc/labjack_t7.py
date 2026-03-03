# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
LabJack T7 ADC driver implementing the abstract ADCBase interface.

Provides analog voltage measurement operations for LabJack T7 devices using the
global handle manager for efficient connection sharing with SPI, DAC, and GPIO.
"""

from __future__ import annotations

import os
import sys

from lager.io.adc.adc_net import ADCBase

DEBUG = bool(os.environ.get("LAGER_ADC_DEBUG"))


def _debug(msg: str) -> None:
    """Debug logging when LAGER_ADC_DEBUG environment variable is set."""
    if DEBUG:
        sys.stderr.write(f"ADC_DEBUG: {msg}\n")
        sys.stderr.flush()


class LabJackADC(ADCBase):
    """
    LabJack T7 ADC implementation.

    Provides analog voltage measurement for LabJack T7 device pins.
    Uses the global LabJack handle manager for efficient connection sharing.

    Pin naming follows LabJack T7 convention:
    - Numeric pins (0-13) map to "AIN0", "AIN1", etc.
    - String pins are used directly as channel names
    """

    def _get_handle(self) -> int:
        """Get LabJack handle from the global handle manager."""
        from lager.io.labjack_handle import get_labjack_handle
        return get_labjack_handle()

    def _get_ljm(self):
        """Get the ljm module from the handle manager."""
        from lager.io.labjack_handle import ljm, _LJM_ERR
        if ljm is None:
            raise RuntimeError(f"LabJack LJM library not available: {_LJM_ERR}")
        return ljm

    def _get_channel_name(self) -> str:
        """Convert pin identifier to LabJack channel name."""
        try:
            pin_num = int(self._pin)
            return f"AIN{pin_num}"
        except (ValueError, TypeError):
            return str(self._pin)

    def input(self) -> float:
        """
        Read the current voltage on the ADC pin.

        Returns:
            Voltage reading in volts as a float

        Raises:
            RuntimeError: If LabJack library is not available
            Exception: For LabJack communication errors
        """
        ljm = self._get_ljm()
        handle = self._get_handle()
        channel_name = self._get_channel_name()

        _debug(f"Reading ADC from channel {channel_name}")
        voltage = ljm.eReadName(handle, channel_name)
        return float(voltage)
