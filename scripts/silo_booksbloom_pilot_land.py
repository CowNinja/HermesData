#!/usr/bin/env python3
"""Controlled Booksbloom residual pilot — direct to Projects shelf, NO Inbox.

Copy-first (evidence zone). Nested under:
  K:/.../Core-Personal/Projects/from-g-drive/Booksbloom/<relpath>

Does not purge G:. Dry-run default; --apply to land.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(r"G:/Booksbloom")
DEST_ROOT = Path(
    r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Projects/from-g-drive/Booksbloom"
)
REG = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-booksbloom-pilot-latest.md")
SKIP_EXT = {".tmp", ".partial", ".crdownload", ".ds_store"}
SKIP_NAME = {"thumbs.db", "desktop.ini"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path, limit: int = 0) -> str | None:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            if limit:
                h.update(f.read(limit))
            else:
                while True:
                    b = f.read(1024 * 1024)
                    if not b:
                        break
                    h.update(b)
        return h.hexdigest()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--max-mb", type=float, default=80.0, help="skip huge media this pilot wave")
    args = ap.parse_args()
    if not SRC.is_dir():
        print(json.dumps({"error": "G:/Booksbloom missing"}))
        return 1

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    now = utc()
    planned = []
    skipped = 0
    for p in SRC.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() in SKIP_NAME or p.suffix.lower() in SKIP_EXT:
            skipped += 1
            continue
        try:
            sz = p.stat().st_size
        except Exception:
            skipped += 1
            continue
        if sz > args.max_mb * 1024 * 1024:
            skipped += 1
            continue
        try:
            rel = p.relative_to(SRC)
        except Exception:
            rel = Path(p.name)
        dest = DEST_ROOT / rel
        if dest.is_file():
            skipped += 1
            continue
        planned.append((p, dest, sz))
        if len(planned) >= args.limit:
            break

    applied = 0
    errors = 0
    con = None
    if args.apply:
        con = sqlite3.connect(str(REG), timeout=120)
        con.execute("PRAGMA busy_timeout=120000")

    for src, dest, sz in planned:
        if not args.apply:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            sh = sha256_file(dest)
            con.execute(
                """INSERT INTO ingest(source_path, dest_path, sha256, size, domain, status,
                   process_status, first_seen, last_seen, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(src),
                    str(dest),
                    sh,
                    sz,
                    "Core-Personal/Projects",
                    "landed",
                    "landed_booksbloom_pilot",
                    now,
                    now,
                    "pilot no-inbox direct shelf",
                ),
            )
            applied += 1
            if applied % 25 == 0:
                con.commit()
        except Exception as e:
            errors += 1
    if con:
        con.commit()
        con.close()

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"""# Booksbloom pilot — {now}

| | |
|--|--|
| Mode | {'APPLY' if args.apply else 'DRY'} |
| Planned | {len(planned)} |
| Applied | {applied} |
| Skipped | {skipped} |
| Errors | {errors} |
| Dest | `{DEST_ROOT}` |
| Rule | **No Inbox** · copy-first · nested origin |
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "apply": args.apply,
                "planned": len(planned),
                "applied": applied,
                "skipped": skipped,
                "errors": errors,
                "dest": str(DEST_ROOT),
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
