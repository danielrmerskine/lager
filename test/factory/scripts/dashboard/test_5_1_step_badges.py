# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class StepOne(Step):
    DisplayName = "Step One"
    def run(self):
        print("Running step one")
        return True

class StepTwo(Step):
    DisplayName = "Step Two"
    def run(self):
        print("Running step two")
        return True

STEPS = [StepOne, StepTwo]
