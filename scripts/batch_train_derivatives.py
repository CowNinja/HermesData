#!/usr/bin/env python3
"""Batch P1 training derivatives under a domain folder (idempotent)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
try:
    from silo_relevance_heuristics import train_meta_flags as _train_meta_flags
except Exception:
    _train_meta_flags = None

SCRIPT = Path(r"D:\HermesData\scripts\training_derivative_text.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default=r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Medical-Records",
    )
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    root = Path(args.root)
    exts = {".pdf", ".txt", ".md", ".csv", ".json"}
    files: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        if p.name.endswith(".meta.json") or ".train." in p.name:
            continue
        if Path(str(p) + ".train.md").exists():
            continue
        files.append(p)
        if len(files) >= args.limit:
            break
    ok = 0
    # optional registry process_status
    try:
        from ingest_registry import connect as reg_connect
        icon = reg_connect()
    except Exception:
        icon = None
    for f in files:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), str(f)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            ok += 1
            if icon is not None:
                try:
                    icon.execute(
                        "UPDATE ingest SET process_status='derivative_ok' WHERE dest_path=? OR dest_path LIKE ?",
                        (str(f), str(f).replace("\\", "/")),
                    )
                except Exception:
                    pass
    if icon is not None:
        try:
            icon.commit()
        except Exception:
            pass
    print(json.dumps({"root": str(root), "attempted": len(files), "ok": ok}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
