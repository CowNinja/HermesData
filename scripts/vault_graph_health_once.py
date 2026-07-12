#!/usr/bin/env python3
"""One-shot Graph Health (manual / recovery). Aligns with canonical pipeline.

ACT then MEASURE (same order as 05:15 gardener + 06:00 hygiene):
  1) refresh_folder_indexes
  2) vault_hub_backlink_pass --apply
  3) vault_wikilink_repair_after_distill
  4) daily-vault-hygiene (measure + optional catch-up)

See: Operations/Vault-Hygiene-Pipeline-Canonical-2026-07-12.md
Skill: productivity/vault-graph-health
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
VAULT = Path(r"D:\PhronesisVault")
PY = sys.executable


def run(args: list[str], timeout: int = 900) -> int:
    print("RUN", " ".join(args))
    try:
        r = subprocess.run(
            args,
            cwd=str(HERMES),
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode
    except subprocess.TimeoutExpired:
        print("TIMEOUT", args)
        return 124


def main() -> int:
    if not VAULT.is_dir():
        print("VAULT_CONFIRMED FAIL")
        return 1
    print(f"VAULT_CONFIRMED={VAULT}")

    steps = [
        ([PY, str(SCRIPTS / "refresh_folder_indexes.py")], 300),
        ([PY, str(SCRIPTS / "vault_hub_backlink_pass.py"), "--apply", "--limit", "150"], 600),
        ([PY, str(SCRIPTS / "vault_wikilink_repair_after_distill.py")], 600),
        ([PY, str(SCRIPTS / "daily-vault-hygiene.py")], 900),
    ]
    worst = 0
    for cmd, to in steps:
        if not Path(cmd[1]).is_file():
            print("MISSING", cmd[1])
            worst = max(worst, 1)
            continue
        code = run(cmd, timeout=to)
        # hub backlink always 0; hygiene lint advisory may soft-fail inside wrapper
        if code != 0:
            print(f"WARN exit {code} for {cmd[1]}")
            worst = max(worst, code if code != 1 else 0)  # treat 1 as soft for hygiene chain
    print("vault_graph_health_once DONE worst=", worst)
    return 0 if worst in (0, 1) else worst


if __name__ == "__main__":
    raise SystemExit(main())
