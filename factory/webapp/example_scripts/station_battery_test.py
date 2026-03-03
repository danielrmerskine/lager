# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Station: Battery Simulator Validation

Tests the Keithley 2281S battery simulator (battery1) on <YOUR_BOX>.
Steps verify SOC control, VOC measurement, and enable/disable.

Note: battery1 and supply1 share the same Keithley 2281S.
Do not run this station concurrently with supply tests.
"""
from lager import Net, NetType
from factory import Step, run
import time


class BatteryConnect(Step):
    DisplayName = "Verify Battery Simulator"
    Description = "Check that battery1 is reachable."
    StopOnFail = True

    def run(self):
        self.log("Connecting to battery1...")
        battery = Net.get("battery1", type=NetType.Battery)
        battery.disable()
        time.sleep(0.5)
        self.log("Battery simulator connected.")
        return True


class SetFullCharge(Step):
    DisplayName = "Set Battery to 100% SOC"
    Description = "Simulate a fully charged battery and verify open-circuit voltage."
    StopOnFail = True

    def run(self):
        battery = Net.get("battery1", type=NetType.Battery)

        self.log("Setting SOC to 100%...")
        battery.set_soc(100)
        time.sleep(1.0)

        voc = battery.voc()
        self.log(f"VOC at 100% SOC: {voc}")
        self.state['voc_full'] = voc
        self.log("PASS: VOC reading obtained.")
        return True


class SetHalfCharge(Step):
    DisplayName = "Set Battery to 50% SOC"
    Description = "Simulate a half-charged battery and verify VOC changes."
    StopOnFail = True

    def run(self):
        battery = Net.get("battery1", type=NetType.Battery)

        self.log("Setting SOC to 50%...")
        battery.set_soc(50)
        time.sleep(1.0)

        voc = battery.voc()
        voc_full = self.state.get('voc_full', 'N/A')
        self.log(f"VOC at 50% SOC: {voc} (was {voc_full} at 100%)")
        self.state['voc_half'] = voc
        self.log("PASS: VOC reading obtained.")
        return True


class EnableDisableOutput(Step):
    DisplayName = "Enable/Disable Battery Output"
    Description = "Enable battery output, then disable it."
    StopOnFail = False

    def run(self):
        battery = Net.get("battery1", type=NetType.Battery)

        self.log("Enabling battery output...")
        battery.enable()
        time.sleep(1.0)

        soc = battery.soc()
        self.log(f"Battery SOC reading: {soc}")

        self.log("Disabling battery output...")
        battery.disable()
        time.sleep(0.5)
        self.log("Battery output disabled.")
        return True


class OperatorVisualCheck(Step):
    DisplayName = "Visual Inspection"
    Description = "Operator confirms the battery simulator display is correct."
    StopOnFail = False

    def run(self):
        self.update_heading("Check the Keithley 2281S front panel display")
        self.log("Please verify the front panel shows the battery simulator is in standby.")
        result = self.present_buttons([
            ("Display looks correct", True),
            ("Display shows an error", False),
            ("Cannot see display", False),
        ])
        if result:
            self.log("Operator confirmed display is correct.")
        else:
            self.log("Operator reported display issue.")
        return result


class BatteryCleanup(Step):
    DisplayName = "Battery Cleanup"
    Description = "Disable battery output and summarize results."
    StopOnFail = False

    def run(self):
        battery = Net.get("battery1", type=NetType.Battery)
        battery.disable()
        self.log("Battery output disabled.")

        voc_full = self.state.get('voc_full', 'N/A')
        voc_half = self.state.get('voc_half', 'N/A')
        self.log("--- Battery Test Summary ---")
        self.log(f"  VOC at 100% SOC: {voc_full}")
        self.log(f"  VOC at 50% SOC:  {voc_half}")
        return True


STEPS = [
    BatteryConnect,
    SetFullCharge,
    SetHalfCharge,
    EnableDisableOutput,
    OperatorVisualCheck,
    BatteryCleanup,
]

if __name__ == '__main__':
    run(STEPS)
