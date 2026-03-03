# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Step script where one step fails. Tests StopOnFail behavior."""

from factory import Step, run


class SetupStep(Step):
    DisplayName = "Setup"
    Description = "Always passes"

    def run(self):
        self.log("Setup complete.")
        return True


class FailingStep(Step):
    DisplayName = "Failing Step"
    Description = "This step always fails"
    StopOnFail = True

    def run(self):
        self.log("About to fail...")
        return False


class NeverReachedStep(Step):
    DisplayName = "Never Reached"
    Description = "Should not execute due to StopOnFail"

    def run(self):
        self.log("This should never print.")
        return True


STEPS = [SetupStep, FailingStep, NeverReachedStep]

run(STEPS)
