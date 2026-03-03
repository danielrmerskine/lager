# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

import sys
for i in range(5):
    print(f"stdout line {i}")
    print(f"stderr line {i}", file=sys.stderr)
