# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Always exits with code 1."""

import sys

print("This script is designed to fail.")
print("Exiting with code 1.", file=sys.stderr)
sys.exit(1)
