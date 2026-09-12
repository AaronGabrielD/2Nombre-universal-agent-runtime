"""Test package for the Universal Agent Runtime."""
from __future__ import annotations

import os

# This value is intentionally test-only and never represents a production secret.
os.environ.setdefault("UAR_EXECUTION_AUTH_SECRET", "unit-test-signing-secret-" + "x" * 48)
