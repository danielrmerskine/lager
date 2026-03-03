# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step, run

class MyStep(Step):
    DisplayName = "My Step"
    def run(self):
        return True

STEPS = [MyStep]
run(STEPS)
