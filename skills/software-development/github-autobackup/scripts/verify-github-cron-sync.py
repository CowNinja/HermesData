#!/usr/bin/env python3
"""Verification script for GitHub repo sync crons (github-autobackup skill).

Run to diagnose "where is the cron" or "unfired" complaints based on GH timestamps.
Captures current state without side effects.

Usage: python D:\\HermesData\\skills\\software-development\\github-autobackup\\scripts\\verify-github-cron-sync.py
"""

import os
import subprocess
from pathlib import Path

CRON_OUTPUT_DIR = Path(r"D:\HermesData\cron\output")
JOBS = {
    "Hermes-Resilience-Backup": "646449c250f1",
    "Git-Repo-Recovery-30m": "cc127b21a784",
}
REPOS = {
    "HermesData": (Path(r"D:\HermesData"), "main"),
    "PhronesisVault": (Path(r"D:\PhronesisVault"), "master"),
}

def main():
    print("## GitHub Sync Cron Verification (github-autobackup)")
    print("Targets: HermesData, PhronesisVault (conditional on changes only)")
    print()

    # Check cron outputs
    for name, jid in JOBS.items():
        out_dir = CRON_OUTPUT_DIR / jid
        if out_dir.exists():
            latest = sorted(out_dir.glob("*.md"), key=os.path.getmtime, reverse=True)
            if latest:
                print(f"Latest {name} log: {latest[0].name}")
                content = latest[0].read_text(errors="ignore")
                for line in content.splitlines():
                    if "Backup" in line or "no changes" in line.lower() or "[OK]" in line or "unpushed" in line.lower():
                        print("  " + line)
        else:
            print(f"No output dir for {name}")

    print()
    # Check .git/config remotes (text only)
    for name, (root, branch) in REPOS.items():
        cfg = root / ".git" / "config"
        if cfg.exists():
            text = cfg.read_text(errors="ignore")
            for line in text.splitlines():
                if "url =" in line or "remote" in line.lower():
                    print(f"{name} config: {line.strip()}")
        else:
            print(f"{name}: no .git/config")

    print("\n[Done] See SKILL.md and references/2026-07-08-github-sync-cron-audit.md for full pattern and recipe.")
    print("Note: GH 'Updated' = last commit, not last cron fire. Conditional pushes are expected.")

if __name__ == "__main__":
    main()
