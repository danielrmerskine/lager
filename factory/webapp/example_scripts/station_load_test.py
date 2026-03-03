# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Station: Supply Under Load

Uses supply1 + eload1 on <YOUR_BOX> to verify the power supply behaves
correctly under different load conditions (constant current).
"""
from lager import Net, NetType
from factory import Step, run
import time


class SelectTestProfile(Step):
    DisplayName = "Select Load Test Profile"
    Description = "Choose which load levels to test."
    StopOnFail = True

    def run(self):
        profile = self.present_radios("Select load test profile:", [
            ("Light load (100mA)", "light"),
            ("Medium load (500mA)", "medium"),
            ("Heavy load (1A)", "heavy"),
        ])
        profiles = {
            "light":  {"cc": 0.1, "label": "100mA"},
            "medium": {"cc": 0.5, "label": "500mA"},
            "heavy":  {"cc": 1.0, "label": "1A"},
        }
        selected = profiles.get(profile, profiles["light"])
        self.state['load_current'] = selected['cc']
        self.state['load_label'] = selected['label']
        self.log(f"Selected profile: {selected['label']}")
        return True


class EnableSupply(Step):
    DisplayName = "Enable Power Supply"
    Description = "Set supply1 to 5V and enable output."
    StopOnFail = True

    def run(self):
        supply = Net.get("supply1", type=NetType.PowerSupply)
        self.log("Setting supply to 5.0V / 2A limit...")
        supply.set_voltage(5.0)
        supply.set_current(2.0)
        supply.enable()
        time.sleep(1.0)

        voltage = supply.voltage()
        self.log(f"Supply voltage (no load): {voltage}V")
        self.state['v_no_load'] = voltage

        if abs(voltage - 5.0) < 0.2:
            self.log("PASS: Supply voltage is correct.")
            return True
        else:
            self.log(f"FAIL: Supply voltage out of range ({voltage}V)")
            return False


class ApplyConstantCurrent(Step):
    DisplayName = "Apply Constant Current Load"
    Description = "Set eload1 to constant current mode and measure supply response."
    StopOnFail = True

    def run(self):
        supply = Net.get("supply1", type=NetType.PowerSupply)
        eload = Net.get("eload1", type=NetType.ELoad)

        target_current = self.state.get('load_current', 0.1)
        label = self.state.get('load_label', '100mA')

        self.log(f"Setting eload to CC mode: {label}...")
        eload.mode('CC')
        eload.current(target_current)
        eload.enable()
        time.sleep(2.0)

        voltage = supply.voltage()
        current = supply.current()
        self.log(f"Under {label} load:")
        self.log(f"  Voltage: {voltage}V")
        self.log(f"  Current: {current}A")

        self.state['v_under_load'] = voltage
        self.state['i_under_load'] = current

        # Voltage should remain within 10% of 5V
        if abs(voltage - 5.0) < 0.5:
            self.log("PASS: Voltage regulation is acceptable.")
            return True
        else:
            self.log("FAIL: Voltage dropped too much under load.")
            return False


class MeasureLoadRegulation(Step):
    DisplayName = "Calculate Load Regulation"
    Description = "Compare no-load and loaded voltage to assess regulation quality."
    StopOnFail = False

    def run(self):
        v_no_load = self.state.get('v_no_load', 5.0)
        v_under_load = self.state.get('v_under_load', 5.0)

        drop = v_no_load - v_under_load
        regulation_pct = (drop / v_no_load) * 100.0 if v_no_load else 0

        self.log(f"No-load voltage:    {v_no_load:.4f}V")
        self.log(f"Loaded voltage:     {v_under_load:.4f}V")
        self.log(f"Voltage drop:       {drop:.4f}V")
        self.log(f"Load regulation:    {regulation_pct:.2f}%")

        self.state['regulation_pct'] = regulation_pct

        # Typical bench supply should have < 1% regulation
        if regulation_pct < 2.0:
            self.log("PASS: Load regulation is within spec.")
            return True
        else:
            self.log(f"WARN: Load regulation is {regulation_pct:.2f}% (expected < 2%)")
            return False


class DisableAll(Step):
    DisplayName = "Disable Supply and Load"
    Description = "Turn off the electronic load and power supply."
    StopOnFail = False

    def run(self):
        eload = Net.get("eload1", type=NetType.ELoad)
        supply = Net.get("supply1", type=NetType.PowerSupply)

        self.log("Disabling eload...")
        eload.disable()
        time.sleep(0.5)

        self.log("Disabling supply...")
        supply.disable()
        time.sleep(0.5)

        self.log("--- Load Test Summary ---")
        self.log(f"  Profile: {self.state.get('load_label', 'N/A')}")
        self.log(f"  No-load voltage: {self.state.get('v_no_load', 'N/A')}V")
        self.log(f"  Loaded voltage:  {self.state.get('v_under_load', 'N/A')}V")
        self.log(f"  Load current:    {self.state.get('i_under_load', 'N/A')}A")
        self.log(f"  Regulation:      {self.state.get('regulation_pct', 'N/A')}%")
        return True


STEPS = [
    SelectTestProfile,
    EnableSupply,
    ApplyConstantCurrent,
    MeasureLoadRegulation,
    DisableAll,
]

if __name__ == '__main__':
    run(STEPS)
