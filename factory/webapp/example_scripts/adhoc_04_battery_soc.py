# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Ad-hoc: Battery SOC Sweep

Sweeps battery1 through several SOC levels (100%, 75%, 50%, 25%)
and reads the open-circuit voltage at each level.

Note: battery1 and supply1 share the same Keithley 2281S on <YOUR_BOX>.
Do not run this script immediately after a supply script without
a short delay to allow the instrument to release.
"""
from lager import Net, NetType
import time
import sys


def main():
    battery = Net.get("battery1", type=NetType.Battery)

    battery.disable()
    time.sleep(0.5)

    soc_levels = [100, 75, 50, 25]
    results = []

    print("Battery SOC Sweep")
    print("=" * 35)

    for level in soc_levels:
        print(f"Setting SOC to {level}%...", end=" ")
        battery.set_soc(level)
        time.sleep(1.0)

        voc = battery.voc()
        print(f"VOC = {voc}")
        results.append((level, voc))

    print()
    print("Summary:")
    print(f"  {'SOC':>5}  {'VOC':>8}")
    print(f"  {'---':>5}  {'---':>8}")
    for level, voc in results:
        print(f"  {level:>4}%  {voc:>8}")

    battery.disable()
    print()
    print("PASS: Battery SOC sweep complete.")


if __name__ == '__main__':
    main()
