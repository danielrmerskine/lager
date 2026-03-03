# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class ButtonTest(Step):
    DisplayName = "Button Test"
    def run(self):
        result = self.choice("Pick one", [("Pass", True), ("Fail", False)])
        return result

STEPS = [ButtonTest]
