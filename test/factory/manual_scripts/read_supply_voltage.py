# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Reads supply1 voltage. Requires real hardware."""

from lager import Net, NetType

supply = Net.get('supply1', type=NetType.PowerSupply)
voltage = supply.voltage()
print(f"Supply1 voltage: {voltage} V")
