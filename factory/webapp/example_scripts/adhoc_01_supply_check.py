# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Ad-hoc: Quick Supply Voltage Check

Sets supply1 to 3.3V, reads back the voltage, and verifies
it is within tolerance. No operator interaction required.
"""
from lager import Net, NetType
import time
import sys


def main():
    supply = Net.get("supply1", type=NetType.PowerSupply)

    # Disable first to start clean
    supply.disable()
    time.sleep(0.5)

    # Test 3.3V
    print("Setting supply1 to 3.3V, 500mA limit...")
    supply.set_voltage(3.3)
    supply.set_current(0.5)
    supply.enable()
    time.sleep(1.0)

    voltage = supply.voltage()
    current = supply.current()
    print(f"Measured: {voltage}V, {current}A")

    if abs(voltage - 3.3) > 0.15:
        print(f"FAIL: Voltage {voltage}V is outside 3.3V +/- 0.15V")
        supply.disable()
        sys.exit(1)

    # Test 5.0V
    print("Setting supply1 to 5.0V, 500mA limit...")
    supply.set_voltage(5.0)
    supply.set_current(0.5)
    time.sleep(1.0)

    voltage = supply.voltage()
    current = supply.current()
    print(f"Measured: {voltage}V, {current}A")

    if abs(voltage - 5.0) > 0.15:
        print(f"FAIL: Voltage {voltage}V is outside 5.0V +/- 0.15V")
        supply.disable()
        sys.exit(1)

    supply.disable()
    print("PASS: All supply voltage checks passed.")


if __name__ == '__main__':
    main()
