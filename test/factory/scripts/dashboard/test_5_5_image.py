# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

from factory import Step

class ImageStep(Step):
    DisplayName = "Image Step"
    Image = "https://via.placeholder.com/150"
    def run(self):
        return True

STEPS = [ImageStep]
