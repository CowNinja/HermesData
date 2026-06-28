#!/usr/bin/env python3
"""Hermes cron: weekly evolve note (delegates to vault script)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(r"D:\PhronesisVault\scripts\discord_weekly_evolve.py")


def main() -> int:
    if not Path(r"D:\PhronesisVault").is_dir():
        print("VAULT_CONFIRMED FAIL")
        return 1
    if not SCRIPT.exists():
        print(f"MISSING {SCRIPT}")
        return 1
    return subprocess.call([sys.executable, str(SCRIPT)])


if __name__ == "__main__":
    raise SystemExit(main())
