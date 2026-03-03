# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Ad-hoc: USB Port Cycle Test

Cycles through USB ports on the Acroname 8-port hub (<YOUR_BOX>),
disabling and re-enabling each one to verify hub control.
"""
from lager import Net, NetType
import time
import sys


def main():
    usb_nets = ["usb1", "usb2", "usb3", "usb4", "usb5", "usb6", "usb7", "usb8"]

    print(f"Testing {len(usb_nets)} USB ports on Acroname hub...")
    print()

    errors = []
    for name in usb_nets:
        try:
            usb = Net.get(name, type=NetType.Usb)

            print(f"{name}: disabling...", end=" ")
            usb.disable()
            time.sleep(0.5)

            print("enabling...", end=" ")
            usb.enable()
            time.sleep(0.5)

            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(name)

    print()
    if errors:
        print(f"FAIL: {len(errors)} port(s) had errors: {', '.join(errors)}")
        sys.exit(1)
    else:
        print(f"PASS: All {len(usb_nets)} USB ports cycled successfully.")


if __name__ == '__main__':
    main()
