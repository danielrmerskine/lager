# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class FailingStep(Step):
    DisplayName = "Failing Step"
    def run(self):
        print("This step fails")
        return False

STEPS = [FailingStep]
