# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class TextInputTest(Step):
    DisplayName = "Text Input Test"
    def run(self):
        value = self.input("Enter a value:")
        print(f"Got: {value}")
        return True

STEPS = [TextInputTest]
