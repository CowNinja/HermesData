#!/usr/bin/env python3
"""Hermes cron entry: daily vault hygiene audit (delegates to PhronesisVault scripts)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VAULT_SCRIPT = Path(r"D:\PhronesisVault\scripts\daily_vault_hygiene_audit.py")
LINK_AUDIT = Path(r"D:\PhronesisVault\scripts\vault_link_audit.py")
LINK_LINT = Path(r"D:\PhronesisVault\scripts\vault_link_lint.py")


def run(script: Path) -> int:
    if not script.exists():
        print(f"MISSING {script}")
        return 1
    return subprocess.call([sys.executable, str(script)])


def main() -> int:
    vault = Path(r"D:\PhronesisVault")
    if not vault.is_dir():
        print("VAULT_CONFIRMED FAIL")
        return 1
    print(f"VAULT_CONFIRMED={vault}")
    # Core hygiene scripts — these MUST pass
    for script in (VAULT_SCRIPT, LINK_AUDIT):
        code = run(script)
        if code != 0:
            print(f"FAIL: {script.name} exited {code}")
            return code
    # Link lint is advisory — report but don't fail
    code = run(LINK_LINT)
    if code != 0:
        print(f"ADVISORY: {LINK_LINT.name} found issues (exit {code}) — see Operations/Vault-Link-Lint-latest.json")
    print("daily-vault-hygiene OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
