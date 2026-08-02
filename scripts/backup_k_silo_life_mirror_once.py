#!/usr/bin/env python3
"""Selective Personal-Digital-Silo signal mirror -> K: (budgeted).

Not a full silo clone. High-signal indexes, manifests, small markdown proofs.
Skips media, bulk ingest, train artifacts when oversized.

Usage:
  python D:/HermesData/scripts/backup_k_silo_life_mirror_once.py
  python D:/HermesData/scripts/backup_k_silo_life_mirror_once.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES = Path(r"D:\HermesData")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
# Also accept D-side pointer if present
SILO_ALT = Path(r"D:\Phronesis-Sovereign\Personal-Digital-Silo")
DEST = Path(r"K:\Hermes-Resilience\mirrors\Personal-Digital-Silo-Signal")
STATE = HERMES / "state" / "backup_k_silo_life_mirror_last.json"

# relative dirs under silo root worth keeping
SIGNAL_DIRS = [
    "",  # top-level md only handled separately
    "Core-Personal",
    "Goals",
    "Extended",
    "Archive",
    "Life-Archive",
    "Medical",
    "Medical-Records",
    "Navy-Service",
    "Digital-Footprint",
]

SIGNAL_NAME_PREFIXES = (
    "00-",
    "Goals-",
    "HERMES_",
    "INDEX",
    "Digital-Twin",
)
SIGNAL_SUFFIXES = (".md", ".json", ".txt", ".csv", ".yaml", ".yml")
MAX_FILE_BYTES = 12 * 1024 * 1024  # 12MB per file
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024  # 4GB budget per run (deepened 2026-08-02)
MAX_FILES = 8000
MAX_DEPTH = 6
SKIP_DIR_NAMES = {
    "node_modules",
    ".git",
    "__pycache__",
    "media",
    "Media",
    "photos",
    "Photos",
    "video",
    "Video",
    "raw",
    "Raw",
    "_Staging-From-G-Drive",
    "_Fused",
    "test-ingest",
    "test-ingest-2026-06-25",
    "test-ingest-2026-06-26-medical-comms-tranche",
    "embeddings",
    "vectors",
    "models",
    "weights",
}


def log(m: str) -> None:
    print(m, flush=True)


def find_silo() -> Path | None:
    if SILO.is_dir():
        return SILO
    if SILO_ALT.is_dir():
        return SILO_ALT
    return None


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.endswith(".train.md")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    root = find_silo()
    if root is None:
        payload = {"ts": ts, "ok": False, "error": "silo_root_missing"}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log("FAIL silo root missing")
        return 2

    DEST.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    total_b = 0
    errors: List[str] = []

    # Top-level signal files
    candidates: List[Path] = []
    for p in root.iterdir():
        if p.is_file() and p.suffix.lower() in SIGNAL_SUFFIXES:
            if p.name.startswith(SIGNAL_NAME_PREFIXES) or p.suffix == ".md":
                if ".train." in p.name:
                    continue
                candidates.append(p)

    walk_subs = (
        "Core-Personal",
        "Extended",
        "Life-Archive",
        "Medical",
        "Medical-Records",
        "Navy-Service",
        "Digital-Footprint",
        "Archive",
        "Goals",
    )
    for sub in walk_subs:
        d = root / sub
        if not d.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = [x for x in dirnames if not should_skip_dir(x)]
            # depth limit (deepened 4 -> MAX_DEPTH)
            rel_depth = Path(dirpath).relative_to(root).parts
            if len(rel_depth) > MAX_DEPTH:
                dirnames[:] = []
                continue
            for fn in filenames:
                if ".train." in fn:
                    continue
                suf = Path(fn).suffix.lower()
                if suf not in SIGNAL_SUFFIXES:
                    continue
                candidates.append(Path(dirpath) / fn)
                if len(candidates) > MAX_FILES * 2:
                    break

    for src in candidates:
        if copied >= MAX_FILES or total_b >= MAX_TOTAL_BYTES:
            skipped += 1
            continue
        try:
            sz = src.stat().st_size
        except OSError:
            skipped += 1
            continue
        if sz > MAX_FILE_BYTES or sz == 0:
            skipped += 1
            continue
        try:
            rel = src.relative_to(root)
        except ValueError:
            skipped += 1
            continue
        dst = DEST / rel
        if args.dry_run:
            copied += 1
            total_b += sz
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # skip if same size+mtime
            if dst.exists():
                ds = dst.stat()
                ss = src.stat()
                if ds.st_size == ss.st_size and int(ds.st_mtime) == int(ss.st_mtime):
                    skipped += 1
                    continue
            shutil.copy2(src, dst)
            copied += 1
            total_b += sz
        except OSError as e:
            errors.append(f"{rel}: {e}"[:160])

    # index crumb on dest
    idx = {
        "ts": ts,
        "source": str(root),
        "copied": copied,
        "skipped": skipped,
        "total_bytes": total_b,
        "errors": errors[:20],
        "budget_files": MAX_FILES,
        "budget_bytes": MAX_TOTAL_BYTES,
    }
    if not args.dry_run:
        (DEST / "00-SIGNAL-MIRROR-MANIFEST.json").write_text(
            json.dumps(idx, indent=2), encoding="utf-8"
        )

    ok = len(errors) < 10 and (copied > 0 or skipped > 0)
    payload = {"ts": ts, "ok": ok, **idx, "dest": str(DEST), "dry_run": args.dry_run}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # refresh parent latest-backup touch via small sidecar
    try:
        man = Path(r"K:\Hermes-Resilience\manifests\silo-signal-last.json")
        man.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        log(f"DONE ok={ok} copied={copied} skipped={skipped} MB={total_b/1e6:.1f} errors={len(errors)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
