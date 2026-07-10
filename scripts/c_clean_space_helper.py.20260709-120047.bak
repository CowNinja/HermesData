#!/usr/bin/env python3
"""
C: Drive Space Helper (Session 13+)
Proactive cleanup for tight C: (target < 20-30 GB free before big runs).
Safe, targeted — only Hermes-related temps and common bloat.
Run with caution; review before delete.
"""

import os
import shutil
from pathlib import Path

TARGETS = [
    Path("C:/Users/CowNi/AppData/Local/Temp"),
    Path("C:/Windows/Temp"),
    Path.home() / "AppData/Local/Temp",
]

HERMES_PATTERNS = ["hermes", "temp-hermes", "verify", "session", "pypdf", "cache"]

def safe_cleanup(dry_run=True):
    freed = 0
    candidates = []
    for base in TARGETS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            try:
                if p.is_file() and any(kw in p.name.lower() for kw in HERMES_PATTERNS):
                    size = p.stat().st_size
                    candidates.append((p, size))
                    if not dry_run:
                        p.unlink(missing_ok=True)
                    freed += size
            except:
                pass
    print(f"Found {len(candidates)} Hermes-related temp files.")
    if dry_run:
        print("DRY RUN — nothing deleted. Total potential: {:.1f} MB".format(freed / 1024**2))
        for p, s in candidates[:20]:
            print(f"  {p} ({s/1024:.0f} KB)")
    else:
        print(f"Deleted. Freed ~{freed/1024**2:.1f} MB")
    return freed

if __name__ == "__main__":
    print("C: Space Helper — dry run first!")
    safe_cleanup(dry_run=True)
    # To actually clean: safe_cleanup(dry_run=False)
    print("\nReview output. Uncomment the live call only if safe.")
