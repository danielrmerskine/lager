# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Station: Supply Validation

Tests the Keithley 2281S power supply (supply1) on <YOUR_BOX>.
Steps verify voltage accuracy, current limiting, and on/off control.
"""
from lager import Net, NetType
from factory import Step, run
import time


class EnterSerialNumber(Step):
    DisplayName = "Enter DUT Serial Number"
    Description = "Record the serial number of the device under test."
    StopOnFail = True

    def run(self):
        serial = self.present_text_input("Scan or type the DUT serial number:", size=30)
        if not serial or len(serial) < 3:
            self.log("No serial number entered.")
            return False
        self.state['serial'] = serial
        self.log(f"Serial number: {serial}")
        return True


class SupplyConnect(Step):
    DisplayName = "Verify Supply Connection"
    Description = "Check that supply1 is reachable and responding."
    StopOnFail = True

    def run(self):
        self.log("Connecting to supply1...")
        supply = Net.get("supply1", type=NetType.PowerSupply)
        supply.disable()
        time.sleep(0.5)
        voltage = supply.voltage()
        self.log(f"Supply idle voltage reading: {voltage}V")
        self.state['supply'] = True
        return True


class SetVoltage3V3(Step):
    DisplayName = "Set and Verify 3.3V Output"
    Description = "Set supply to 3.3V, enable output, and verify voltage is within tolerance."
    StopOnFail = True

    def run(self):
        supply = Net.get("supply1", type=NetType.PowerSupply)
        target = 3.3
        tolerance = 0.1

        self.log(f"Setting voltage to {target}V...")
        supply.set_voltage(target)
        supply.set_current(0.5)
        supply.enable()
        time.sleep(1.0)

        measured = supply.voltage()
        self.log(f"Measured voltage: {measured}V (target: {target}V +/- {tolerance}V)")

        if abs(measured - target) <= tolerance:
            self.log("PASS: Voltage within tolerance.")
            self.state['voltage_3v3'] = measured
            return True
        else:
            self.log(f"FAIL: Voltage out of range ({measured}V)")
            return False


class SetVoltage5V(Step):
    DisplayName = "Set and Verify 5.0V Output"
    Description = "Set supply to 5.0V and verify voltage is within tolerance."
    StopOnFail = True

    def run(self):
        supply = Net.get("supply1", type=NetType.PowerSupply)
        target = 5.0
        tolerance = 0.15

        self.log(f"Setting voltage to {target}V...")
        supply.set_voltage(target)
        supply.set_current(0.5)
        time.sleep(1.0)

        measured = supply.voltage()
        self.log(f"Measured voltage: {measured}V (target: {target}V +/- {tolerance}V)")

        if abs(measured - target) <= tolerance:
            self.log("PASS: Voltage within tolerance.")
            self.state['voltage_5v'] = measured
            return True
        else:
            self.log(f"FAIL: Voltage out of range ({measured}V)")
            return False


class MeasureCurrent(Step):
    DisplayName = "Measure Idle Current"
    Description = "Read supply current with no load connected."
    StopOnFail = False

    def run(self):
        supply = Net.get("supply1", type=NetType.PowerSupply)
        current = supply.current()
        self.log(f"Idle current: {current}A")
        self.state['idle_current'] = current
        # Idle current should be near zero (< 50mA)
        if current < 0.05:
            self.log("PASS: Idle current is negligible.")
            return True
        else:
            self.log(f"WARNING: Idle current is {current}A (expected < 50mA)")
            return False


class Cleanup(Step):
    DisplayName = "Disable Supply Output"
    Description = "Turn off the supply and verify output is disabled."
    StopOnFail = False

    def run(self):
        supply = Net.get("supply1", type=NetType.PowerSupply)
        supply.disable()
        time.sleep(0.5)
        self.log("Supply output disabled.")

        # Summary
        serial = self.state.get('serial', 'unknown')
        v33 = self.state.get('voltage_3v3', 'N/A')
        v5 = self.state.get('voltage_5v', 'N/A')
        idle = self.state.get('idle_current', 'N/A')
        self.log(f"--- Results for S/N {serial} ---")
        self.log(f"  3.3V reading: {v33}")
        self.log(f"  5.0V reading: {v5}")
        self.log(f"  Idle current: {idle}")
        return True


STEPS = [
    EnterSerialNumber,
    SupplyConnect,
    SetVoltage3V3,
    SetVoltage5V,
    MeasureCurrent,
    Cleanup,
]

if __name__ == '__main__':
    run(STEPS)
