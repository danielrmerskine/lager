# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class ButtonStep(Step):
    DisplayName = "Button Test"
    def run(self):
        choice = self.choice("Pick one", ["Option A", "Option B"])
        print(f"User chose: {choice}")
        return True

STEPS = [ButtonStep]
