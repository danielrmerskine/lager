# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Reads ADC from adc1. Requires real hardware."""

from lager import Net, NetType

adc = Net.get('adc1', type=NetType.ADC)
voltage = adc.input()
print(f"ADC1 voltage: {voltage} V")
