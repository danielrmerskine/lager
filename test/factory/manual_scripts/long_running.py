# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Prints lines with sleep(1) for 10 seconds. Tests SSE streaming + cancel."""

import time

for i in range(10):
    print(f"Tick {i + 1} of 10")
    time.sleep(1)

print("Done -- all 10 ticks completed.")
