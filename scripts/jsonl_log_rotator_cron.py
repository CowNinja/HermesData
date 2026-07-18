#!/usr/bin/env python3
"""Hermes no_agent entry: rotate known fat Phronesis/Hermes logs.

Silent when nothing rotated (--silent-ok). Non-empty stdout only if rotation
happened (ops notice under deliver=local). Exit 0 always on successful scan.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonl_log_rotator import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["--once", "--mode", "copytruncate", "--silent-ok"]))
