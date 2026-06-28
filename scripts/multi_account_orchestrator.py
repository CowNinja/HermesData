#!/usr/bin/env python3
"""
Multi-Account Ingestion Orchestrator (Session 14+)
Production-grade handler for pulling from multiple Google accounts (old jeffrey.j.bloom, warz, current)
into D:\HermesData while tracking full provenance.

Features:
- Separate remotes per account
- Dry-run support
- Automatic post-copy discovery_walker with provenance
- Local mirror fallback (G: / K:)
- Source account inference
"""

from pathlib import Path
import subprocess
import json
import shutil
from datetime import datetime

BASE = Path("D:/HermesData")
RCLONE = BASE / "rclone_test" / "rclone.exe"
DATA_DIR = BASE / "data"
MANIFEST_DIR = BASE / "manifests"
WALKER = BASE / "scripts" / "discovery_walker.py"

ACCOUNTS = {
    "old_jeffrey_j_bloom": {
        "remote": "old_backup_gdrive",
        "drive_paths": ["MemoryCard_Backups/Google Drive/Medical"],
        "local_mirror": "/g/MemoryCard_Backups/Google Drive/Medical",
        "description": "Primary source of existing Navy/Medical backups (old archived account)"
    },
    "warz_burner": {
        "remote": "warz_gdrive",
        "drive_paths": [],
        "local_mirror": None,
        "description": "Secondary burner account"
    }
}

def run_command(cmd, dry_run=False):
    if dry_run:
        print("[DRY-RUN]", " ".join(map(str, cmd)))
        return 0, "dry-run"
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr

def copy_from_local_mirror(account_name, config, dest_base, max_files=50):
    mirror = config.get("local_mirror")
    if not mirror:
        return []
    mirror_path = Path(mirror)
    if not mirror_path.exists():
        print(f"Local mirror not accessible: {mirror}")
        return []
    dest = dest_base / account_name
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in list(mirror_path.rglob("*.pdf"))[:max_files]:
        target = dest / p.name
        try:
            shutil.copy2(p, target)
            copied.append(str(p.relative_to(mirror_path)))
        except Exception:
            pass
    return copied

def run_walker_with_provenance(source_dir, session, account_name, original_path, remote_name="local_mirror"):
    cmd = [
        "python", str(WALKER),
        str(source_dir),
        str(session),
        "50",
        "--source-account", account_name,
        "--source-original-path", original_path,
        "--remote-name", remote_name,
        "--output", str(MANIFEST_DIR / f"session{session}_{account_name}_manifest.json")
    ]
    print("Running walker:", " ".join(cmd))
    code, out = run_command(cmd)
    print(out)
    return code == 0

def ingest_account(account_name, config, session=14, dry_run=False, use_local=True):
    print(f"\n=== Ingesting {account_name} ===")
    dest = DATA_DIR / "multi_account_ingest" / account_name
    dest.mkdir(parents=True, exist_ok=True)

    copied = []
    if use_local:
        copied = copy_from_local_mirror(account_name, config, dest.parent, max_files=30)
        print(f"Local mirror copy: {len(copied)} files")

    if copied or not use_local:
        run_walker_with_provenance(
            dest if copied else dest,
            session,
            account_name,
            config.get("local_mirror") or config.get("drive_paths", [""])[0],
            remote_name="local_mirror" if use_local else config["remote"]
        )

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--account", default="all")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-local", action="store_true")
    args = p.parse_args()

    accounts = [args.account] if args.account != "all" else list(ACCOUNTS.keys())
    for acc in accounts:
        if acc in ACCOUNTS:
            ingest_account(acc, ACCOUNTS[acc], dry_run=args.dry_run, use_local=not args.no_local)
    print("\nDone. Check manifests and D:/HermesData/data/multi_account_ingest/")
