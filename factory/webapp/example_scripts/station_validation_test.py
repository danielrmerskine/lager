# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Station: Framework Validation

Exercises every feature of the Step framework and the Lager Python API.
Uses the Acroname USB hub, Keithley 2281S battery simulator, and
Rigol DL3021 electronic load for hardware interaction.
Use this to verify the Lines/Stations pipeline end-to-end.
"""
from factory import Step, run
from lager import Net, NetType, get_available_instruments
import time


class Welcome(Step):
    DisplayName = "Welcome"
    Description = "Initialize the test run and verify basic framework operations."
    StopOnFail = True

    def run(self):
        self.update_heading("Framework Validation Test")
        self.log("Starting framework validation...")
        self.log("This test exercises every interactive control type")
        self.log("and verifies state passing between steps.")
        self.state['started'] = True
        self.state['steps_completed'] = []
        self.state['steps_completed'].append('welcome')
        return True


class InventoryStep(Step):
    DisplayName = "Box Inventory"
    Description = "List all configured nets and instruments on the box."
    StopOnFail = True

    def run(self):
        self.update_heading("Lager API: Box Inventory")

        # List saved nets
        self.log("Calling Net.list_saved()...")
        nets = Net.list_saved()
        self.log(f"Found {len(nets)} configured net(s):")
        for net in nets:
            self.log(f"  {net['name']} (role: {net['role']})")

        # List instruments
        self.log("")
        self.log("Calling get_available_instruments()...")
        instruments = get_available_instruments()
        self.log(f"Found {len(instruments)} instrument(s) in inventory:")
        for instr in instruments:
            name = instr.get('name', 'unknown')
            addr = instr.get('address', 'N/A')
            self.log(f"  {name} ({addr})")

        self.state['net_count'] = len(nets)
        self.state['net_names'] = [n['name'] for n in nets]
        self.state['instrument_count'] = len(instruments)
        self.state['instrument_names'] = [i.get('name', 'unknown') for i in instruments]
        self.state['steps_completed'].append('inventory')
        return True


class USBPortCycleStep(Step):
    DisplayName = "USB Port Cycle"
    Description = "Disable and re-enable a USB port on the Acroname hub via Net.get()."
    StopOnFail = False

    def run(self):
        self.update_heading("Lager API: USB Port Cycle")
        self.log("Getting usb1 net via Net.get('usb1', type=NetType.Usb)...")
        usb = Net.get('usb1', type=NetType.Usb)

        self.log("Disabling usb1...")
        usb.disable()
        time.sleep(1.0)

        self.log("Re-enabling usb1...")
        usb.enable()
        time.sleep(1.0)

        self.log("PASS: USB port cycle completed successfully.")
        self.state['usb_cycle'] = True
        self.state['steps_completed'].append('usb_cycle')
        return True


class BatteryStep(Step):
    DisplayName = "Battery Simulator"
    Description = "Exercise the Keithley 2281S battery simulator API (battery1)."
    StopOnFail = False

    def run(self):
        from lager.power.battery import dispatcher as bat

        self.update_heading("Lager API: Battery Simulator")
        self.log("Using battery dispatcher directly (bypasses hardware_service)...")

        self.log("Configuring battery simulator...")
        bat.set_soc('battery1', value=75.0)
        self.log("  Set SOC to 75%")

        bat.set_capacity('battery1', value=2.0)
        self.log("  Set capacity to 2.0 Ah")

        bat.set_current_limit('battery1', value=1.0)
        self.log("  Set current limit to 1.0 A")

        self.log("Enabling battery output...")
        bat.enable_battery('battery1')
        time.sleep(1.0)

        self.log("Reading measurements...")
        tv = bat.terminal_voltage('battery1')
        curr = bat.current('battery1')
        self.log(f"  Terminal voltage: {tv} V")
        self.log(f"  Current: {curr} A")

        self.log("Disabling battery output...")
        bat.disable_battery('battery1')

        self.state['battery_voltage'] = tv
        self.state['battery_current'] = curr
        self.log("PASS: Battery simulator test completed.")
        self.state['steps_completed'].append('battery')
        return True


class ELoadStep(Step):
    DisplayName = "Electronic Load"
    Description = "Exercise the Rigol DL3021 electronic load API (eload1)."
    StopOnFail = False

    def run(self):
        from lager.power.eload.dispatcher import _dispatcher as eload_dispatcher

        self.update_heading("Lager API: Electronic Load")
        self.log("Using eload dispatcher directly (bypasses hardware_service)...")

        eload = eload_dispatcher.resolve_driver('eload1')

        self.log("Querying current mode...")
        current_mode = eload.mode()
        self.log(f"  Current mode: {current_mode}")

        self.log("Setting mode to CC (constant current)...")
        eload.mode('CC')

        self.log("Setting current to 0.1 A...")
        eload.current(0.1)

        self.log("Reading CC setpoint back...")
        cc_value = eload.current()
        self.log(f"  CC setpoint: {cc_value} A")

        self.log("Enabling eload input...")
        eload.enable()
        time.sleep(1.0)

        self.log("Reading measurements...")
        mv = eload.measured_voltage()
        mc = eload.measured_current()
        mp = eload.measured_power()
        self.log(f"  Measured voltage: {mv} V")
        self.log(f"  Measured current: {mc} A")
        self.log(f"  Measured power:   {mp} W")

        self.log("Disabling eload input...")
        eload.disable()

        self.state['eload_mode'] = current_mode
        self.state['eload_voltage'] = mv
        self.state['eload_current'] = mc
        self.state['eload_power'] = mp
        self.log("PASS: Electronic load test completed.")
        self.state['steps_completed'].append('eload')
        return True


class TextInputStep(Step):
    DisplayName = "Text Input"
    Description = "Test the text input control."
    StopOnFail = True

    def run(self):
        self.update_heading("Text Input Test")
        name = self.present_text_input("Enter your name (any text):", size=30)
        if not name or len(name.strip()) == 0:
            self.log("No text entered.")
            return False
        self.state['operator_name'] = name.strip()
        self.log(f"Received text input: {name.strip()}")
        self.state['steps_completed'].append('text_input')
        return True


class ButtonsStep(Step):
    DisplayName = "Buttons"
    Description = "Test the buttons control with string return values."
    StopOnFail = True

    def run(self):
        self.update_heading("Buttons Test")
        self.log("Choose any color -- all choices pass this step.")
        color = self.present_buttons([
            ("Red", "red"),
            ("Green", "green"),
            ("Blue", "blue"),
        ])
        self.state['chosen_color'] = color
        self.log(f"Button selected: {color}")
        self.state['steps_completed'].append('buttons')
        return True


class PassFailStep(Step):
    DisplayName = "Pass / Fail"
    Description = "Test the pass/fail buttons and verify state from previous steps."
    StopOnFail = True

    def run(self):
        name = self.state.get('operator_name', 'unknown')
        self.update_heading(f"Pass/Fail Test for {name}")
        self.log(f"Operator from step 2: {name}")
        self.log("Click Pass to continue, or Fail to stop the run.")
        result = self.present_pass_fail_buttons()
        self.state['pass_fail_result'] = result
        self.log(f"Pass/Fail result: {result}")
        if result:
            self.state['steps_completed'].append('pass_fail')
        return result


class RadioStep(Step):
    DisplayName = "Radio Buttons"
    Description = "Test radio button selection (single choice)."
    StopOnFail = False

    def run(self):
        self.update_heading("Radio Buttons Test")
        choice = self.present_radios("Pick a priority level:", [
            ("Low", "low"),
            ("Medium", "medium"),
            ("High", "high"),
            ("Critical", "critical"),
        ])
        self.state['priority'] = choice
        self.log(f"Radio selected: {choice}")
        self.state['steps_completed'].append('radios')
        return True


class CheckboxStep(Step):
    DisplayName = "Checkboxes"
    Description = "Test checkbox selection (multiple choices)."
    StopOnFail = False

    def run(self):
        self.update_heading("Checkboxes Test")
        self.log("Select one or more features to enable.")
        selected = self.present_checkboxes("Select features:", [
            ("Logging", "logging"),
            ("Metrics", "metrics"),
            ("Alerts", "alerts"),
            ("Debug Mode", "debug"),
        ])
        self.state['features'] = selected
        self.log(f"Checkboxes selected: {selected}")
        self.state['steps_completed'].append('checkboxes')
        return True


class SelectStep(Step):
    DisplayName = "Select Dropdowns"
    Description = "Test single-select and multi-select dropdowns in one step."
    StopOnFail = False

    def run(self):
        self.update_heading("Select Dropdown Test")

        # Single select
        self.log("--- Single select ---")
        region = self.present_select("Choose a region:", [
            ("US East", "us-east"),
            ("US West", "us-west"),
            ("Europe", "eu"),
            ("Asia Pacific", "apac"),
        ])
        self.state['region'] = region
        self.log(f"Single select: {region}")

        # Multi select
        self.log("--- Multi select ---")
        tags = self.present_select("Choose tags:", [
            ("Production", "prod"),
            ("Staging", "staging"),
            ("Development", "dev"),
            ("QA", "qa"),
        ], allow_multiple=True)
        self.state['tags'] = tags
        self.log(f"Multi select: {tags}")

        self.state['steps_completed'].append('selects')
        return True


class LinkStep(Step):
    DisplayName = "Link Display"
    Description = "Test link rendering and the Link class attribute."
    Link = "https://docs.example.com"
    StopOnFail = False

    def run(self):
        self.update_heading("Link Test")
        self.log("Rendering an inline link via present_link()...")
        self.present_link("https://docs.example.com", text="Lager Documentation")
        self.log("The sidebar should also show the Link class attribute.")
        self.state['steps_completed'].append('link')
        return True


class StateVerification(Step):
    DisplayName = "State Verification"
    Description = "Validate that state accumulated correctly across all previous steps."
    StopOnFail = True

    def run(self):
        self.update_heading("Verifying Accumulated State")
        errors = []

        # Check started flag
        if not self.state.get('started'):
            errors.append("Missing 'started' flag from Welcome step")

        # Check inventory results
        if not isinstance(self.state.get('net_count'), int):
            errors.append("Missing 'net_count' from InventoryStep")
        if not isinstance(self.state.get('net_names'), list):
            errors.append("Missing 'net_names' from InventoryStep")
        if not isinstance(self.state.get('instrument_count'), int):
            errors.append("Missing 'instrument_count' from InventoryStep")
        if not isinstance(self.state.get('instrument_names'), list):
            errors.append("Missing 'instrument_names' from InventoryStep")

        # Check text input
        if not self.state.get('operator_name'):
            errors.append("Missing 'operator_name' from TextInputStep")

        # Check buttons
        if self.state.get('chosen_color') not in ('red', 'green', 'blue'):
            errors.append(f"Invalid 'chosen_color': {self.state.get('chosen_color')}")

        # Check pass/fail
        if self.state.get('pass_fail_result') is not True:
            errors.append("'pass_fail_result' is not True")

        # Check radios
        if self.state.get('priority') not in ('low', 'medium', 'high', 'critical'):
            errors.append(f"Invalid 'priority': {self.state.get('priority')}")

        # Check checkboxes (should be a list)
        features = self.state.get('features')
        if not isinstance(features, list):
            errors.append(f"'features' is not a list: {type(features)}")

        # Check selects
        if not self.state.get('region'):
            errors.append("Missing 'region' from SelectStep")
        if not isinstance(self.state.get('tags'), list):
            errors.append(f"'tags' is not a list: {type(self.state.get('tags'))}")

        # Check step completion tracking
        expected = ['welcome', 'inventory', 'usb_cycle', 'battery', 'eload',
                     'text_input', 'buttons', 'pass_fail',
                     'radios', 'checkboxes', 'selects', 'link']
        completed = self.state.get('steps_completed', [])
        missing = [s for s in expected if s not in completed]
        if missing:
            errors.append(f"Missing from steps_completed: {missing}")

        # Report
        if errors:
            self.log("State verification FAILED:")
            for e in errors:
                self.log(f"  - {e}")
            return False

        self.log("All state checks passed:")
        self.log(f"  net_count       = {self.state['net_count']}")
        self.log(f"  instruments     = {self.state['instrument_names']}")
        self.log(f"  usb_cycle       = {self.state.get('usb_cycle', 'skipped')}")
        self.log(f"  battery_voltage = {self.state.get('battery_voltage', 'skipped')}")
        self.log(f"  eload_voltage   = {self.state.get('eload_voltage', 'skipped')}")
        self.log(f"  operator_name   = {self.state['operator_name']}")
        self.log(f"  chosen_color  = {self.state['chosen_color']}")
        self.log(f"  pass_fail     = {self.state['pass_fail_result']}")
        self.log(f"  priority      = {self.state['priority']}")
        self.log(f"  features      = {self.state['features']}")
        self.log(f"  region        = {self.state['region']}")
        self.log(f"  tags          = {self.state['tags']}")
        self.log(f"  steps_completed = {completed}")
        self.state['steps_completed'].append('state_verify')
        return True


class Summary(Step):
    DisplayName = "Final Confirmation"
    Description = "Review results and confirm the test run."
    StopOnFail = False

    def run(self):
        self.update_heading("Validation Complete")
        self.log("All framework features have been exercised.")
        self.log(f"Operator: {self.state.get('operator_name', 'N/A')}")
        self.log(f"Steps completed: {len(self.state.get('steps_completed', []))}")
        self.log("Click Pass to mark the run as successful.")
        result = self.present_pass_fail_buttons()
        if result:
            self.state['steps_completed'].append('summary')
        return result


class CleanupFinalizer(Step):
    DisplayName = "Cleanup"
    Description = "Finalizer that always runs, even after StopOnFail abort."
    StopOnFail = False

    def run(self):
        completed = self.state.get('steps_completed', [])
        self.log(f"Finalizer running. Steps completed: {len(completed)}/{14}")
        self.log(f"  Completed: {completed}")
        self.log("Cleanup complete. No hardware to release.")
        return True


STEPS = [
    Welcome,
    InventoryStep,
    USBPortCycleStep,
    BatteryStep,
    ELoadStep,
    TextInputStep,
    ButtonsStep,
    PassFailStep,
    RadioStep,
    CheckboxStep,
    SelectStep,
    LinkStep,
    StateVerification,
    Summary,
]

if __name__ == '__main__':
    run(STEPS, finalizer_cls=CleanupFinalizer)
