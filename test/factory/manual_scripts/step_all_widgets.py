# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Step script exercising every present_* method."""

from factory import Step, run


class ButtonStep(Step):
    DisplayName = "Button Demo"
    Description = "Tests present_buttons"

    def run(self):
        result = self.present_buttons([
            ("Option A", "a"),
            ("Option B", "b"),
            ("Option C", "c"),
        ])
        self.log(f"Selected: {result}")
        return result is not None


class TextInputStep(Step):
    DisplayName = "Text Input Demo"
    Description = "Tests present_text_input"

    def run(self):
        value = self.present_text_input("Enter a serial number:", size=30)
        self.log(f"Entered: {value}")
        self.state['serial'] = value
        return bool(value)


class RadioStep(Step):
    DisplayName = "Radio Button Demo"
    Description = "Tests present_radios with tuples"

    def run(self):
        result = self.present_radios("Select board revision:", [
            ("Rev A", "rev_a"),
            ("Rev B", "rev_b"),
            ("Rev C", "rev_c"),
        ])
        self.log(f"Selected revision: {result}")
        return result is not None


class CheckboxStep(Step):
    DisplayName = "Checkbox Demo"
    Description = "Tests present_checkboxes"

    def run(self):
        result = self.present_checkboxes("Select completed checks:", [
            "Solder joints",
            "Component placement",
            "Thermal paste",
        ])
        self.log(f"Checked: {result}")
        return len(result) > 0


class SelectStep(Step):
    DisplayName = "Dropdown Demo"
    Description = "Tests present_select"

    def run(self):
        result = self.present_select("Pick a test fixture:", [
            ("Fixture 1", "f1"),
            ("Fixture 2", "f2"),
            ("Fixture 3", "f3"),
        ])
        self.log(f"Selected fixture: {result}")
        return result is not None


class HeadingAndLinkStep(Step):
    DisplayName = "Heading, Link, and Image Demo"
    Description = "Tests non-interactive present methods"

    def run(self):
        self.update_heading("Final verification step")
        self.present_link("https://docs.lagerdata.com", "Lager Documentation")
        self.log("Non-interactive methods completed.")
        return self.present_pass_fail_buttons()


STEPS = [
    ButtonStep,
    TextInputStep,
    RadioStep,
    CheckboxStep,
    SelectStep,
    HeadingAndLinkStep,
]

run(STEPS)
