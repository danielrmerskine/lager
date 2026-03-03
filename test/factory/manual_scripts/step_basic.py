# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Factory Step script with 3 simple steps using Pass/Fail buttons."""

from factory import Step, run


class VisualInspection(Step):
    DisplayName = "Visual Inspection"
    Description = "Check the board for physical defects"

    def run(self):
        self.log("Inspect the board under the magnifier.")
        return self.present_pass_fail_buttons()


class PowerLedCheck(Step):
    DisplayName = "Power LED Check"
    Description = "Verify the power LED is green"

    def run(self):
        self.log("Look at the power LED on the board.")
        return self.present_pass_fail_buttons()


class LabelCheck(Step):
    DisplayName = "Label Check"
    Description = "Verify the serial number label is present"

    def run(self):
        self.log("Check that the serial number label is applied.")
        return self.present_pass_fail_buttons()


STEPS = [VisualInspection, PowerLedCheck, LabelCheck]

run(STEPS)
