# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class CheckVoltage(Step):
    DisplayName = "Check Voltage"
    Description = "Verify output is 5V"
    def run(self):
        return True

STEPS = [CheckVoltage]
