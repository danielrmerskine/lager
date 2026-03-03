# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Ad-hoc: Supply + Electronic Load Test

Enables supply1 at 5V, applies a 200mA constant-current load via
eload1, measures the resulting voltage and current, then cleans up.
"""
from lager import Net, NetType
import time
import sys


def main():
    supply = Net.get("supply1", type=NetType.PowerSupply)
    eload = Net.get("eload1", type=NetType.ELoad)

    try:
        # Set up supply
        print("Setting supply1 to 5.0V / 2A limit...")
        supply.set_voltage(5.0)
        supply.set_current(2.0)
        supply.enable()
        time.sleep(1.0)

        v_no_load = supply.voltage()
        print(f"No-load voltage: {v_no_load}V")

        # Apply load
        print("Applying 200mA constant current via eload1...")
        eload.mode('CC')
        eload.current(0.2)
        eload.enable()
        time.sleep(2.0)

        v_loaded = supply.voltage()
        i_loaded = supply.current()
        print(f"Loaded voltage:  {v_loaded}V")
        print(f"Supply current:  {i_loaded}A")

        # Check results
        drop = v_no_load - v_loaded
        print(f"Voltage drop:    {drop:.4f}V")

        if abs(v_loaded - 5.0) > 0.5:
            print(f"FAIL: Voltage {v_loaded}V is too far from 5.0V under load")
            sys.exit(1)

        if i_loaded < 0.1:
            print(f"FAIL: Current {i_loaded}A is too low (expected ~200mA)")
            sys.exit(1)

        print("PASS: Supply operates correctly under 200mA load.")

    finally:
        # Always clean up
        print("Disabling eload and supply...")
        eload.disable()
        time.sleep(0.3)
        supply.disable()
        print("Cleanup complete.")


if __name__ == '__main__':
    main()
