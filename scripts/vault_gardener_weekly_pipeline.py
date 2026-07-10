#!/usr/bin/env python3
"""Weekly vault gardener pipeline (system mechanics — NOT only VaultWalker).

Order:
  1) gardener_phase_b_proposals.py  (propose clusters)
  2) optional auto-safe waves stay manual/gated; this pipeline does hygiene
  3) vault_wikilink_repair_after_distill.py
  4) refresh_folder_indexes.py
  5) fill_missing_indexes.py (gaps)

VaultWalker = walk/index/light classify (daily dry-run).
This pipeline = distill hygiene + links + maps (weekly).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
VAULT = Path(r"D:\PhronesisVault")
LOG = HERMES / "logs" / "vault-gardener-weekly-latest.txt"


def run(name: str) -> tuple[int, str]:
    path = SCRIPTS / name
    if not path.is_file():
        return 0, f"SKIP missing {name}"
    r = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        cwd=str(HERMES),
    )
    out = ((r.stdout or "") + (r.stderr or ""))[-2000:]
    return r.returncode, out


def main() -> int:
    steps = [
        "gardener_phase_b_proposals.py",
        "vault_wikilink_repair_after_distill.py",
        "refresh_folder_indexes.py",
        "fill_missing_indexes.py",
    ]
    lines = [f"=== vault_gardener_weekly_pipeline {datetime.now(timezone.utc).isoformat()} ==="]
    worst = 0
    for s in steps:
        code, out = run(s)
        worst = max(worst, code if code else 0)
        lines.append(f"\n## {s} exit={code}\n{out}\n")
        print(f"{s}: exit={code}")
    # receipt
    rec = VAULT / "Operations" / "logs" / f"vault-gardener-weekly-{datetime.now().strftime('%Y-%m-%d')}.md"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(
        f"# Vault Gardener Weekly Pipeline\n\n"
        f"See also [[Operations/Vault-Gardener-Automation-System-2026-07-10]]\n\n"
        + "\n".join(f"- step `{s}`" for s in steps)
        + "\n",
        encoding="utf-8",
    )
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(f"score pipeline worst_exit={worst} log={LOG}")
    return 0 if worst == 0 else worst


if __name__ == "__main__":
    raise SystemExit(main())
