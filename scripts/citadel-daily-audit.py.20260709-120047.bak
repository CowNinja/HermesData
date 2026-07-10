#!/usr/bin/env python3
"""Hermes cron: daily Citadel channel audit + optional stack-health one-liner to vault."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
AUDIT = VAULT / "scripts" / "citadel_channel_audit.py"
ORCH = VAULT / "Discord" / "Meta" / "stack-health.md"


def main() -> int:
    if not VAULT.is_dir():
        print("VAULT_CONFIRMED FAIL")
        return 1
    code = subprocess.call([sys.executable, str(AUDIT)])
    if code != 0:
        return code
    line = f"\n- Citadel audit cron {datetime.now().strftime('%Y-%m-%d %H:%M')} — see [[Discord/Meta/citadel-channel-audit-latest]]\n"
    if ORCH.exists():
        text = ORCH.read_text(encoding="utf-8")
        if line.strip() not in text:
            ORCH.write_text(text + line, encoding="utf-8")
    print("citadel-daily-audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
