# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Step script with STEPS list but no factory.run() call.

Tests the auto-wrapper generation in step_runner.py -- the runner should
detect STEPS without run() and generate a wrapper that calls
factory.run(STEPS) automatically.
"""

from factory import Step


class StepOne(Step):
    DisplayName = "Auto-Wrapper Step 1"
    Description = "First step in auto-wrapped script"

    def run(self):
        self.log("Step 1 executing via auto-wrapper.")
        return self.present_pass_fail_buttons()


class StepTwo(Step):
    DisplayName = "Auto-Wrapper Step 2"
    Description = "Second step in auto-wrapped script"

    def run(self):
        self.log("Step 2 executing via auto-wrapper.")
        return self.present_pass_fail_buttons()


STEPS = [StepOne, StepTwo]
