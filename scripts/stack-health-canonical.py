#!/usr/bin/env python3
"""REDIRECT 2026-08-05 (P4 ensure collapse) -> solid_stack_law_once --status."""
from __future__ import annotations

import sys
from pathlib import Path

sys.argv = [
    sys.argv[0],
    "--from",
    "stack-health-canonical.py",
    "--status",
    "--message",
    "Canonical health is solid_stack_law_once --status / speak-and-trust.",
]
sys.path.insert(0, str(Path(__file__).resolve().parent / "ops"))
from stack_recovery_redirect import main

if __name__ == "__main__":
    raise SystemExit(main())
