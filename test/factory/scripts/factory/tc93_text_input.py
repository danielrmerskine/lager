# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class InputStep(Step):
    DisplayName = "Text Input Test"
    def run(self):
        val = self.input("Enter a value:")
        print(f"Got: {val}")
        return True

STEPS = [InputStep]
