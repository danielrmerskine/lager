# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class LinkStep(Step):
    DisplayName = "Link Step"
    Link = "https://docs.lagerdata.com"
    def run(self):
        return True

STEPS = [LinkStep]
