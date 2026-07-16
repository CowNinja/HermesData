#!/usr/bin/env python3
"""Controlled Booksbloom residual pilot — direct to Projects shelf, NO Inbox.

Copy-first (evidence zone). Nested under:
  K:/.../Core-Personal/Projects/from-g-drive/Booksbloom/<relpath>

Does not purge G:. Dry-run default; --apply to land.

Hang-fix 2026-07-14:
- Load already-landed source_path set from registry (O(1) skip) — no re-stat of 70k+ dests.
- Fast fingerprint (size+mtime+first 4MB) instead of full-file SHA for land speed.
- Skip junk tree segments (AppData, caches, node_modules, browser profiles).
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
SKIP_EXT = {".tmp", ".partial", ".crdownload", ".ds_store", ".pyc", ".pyo"}
SKIP_NAME = {"thumbs.db", "desktop.ini", ".ds_store"}
# residual polish: do not re-land whole-PC dump noise
JUNK_PARTS = {
    "appdata",
    "application data",
    "local settings",
    "temp",
    "tmp",
    "cache",
    "caches",
    "node_modules",
    ".git",
    "__pycache__",
    "recycle.bin",
    "$recycle.bin",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "mozilla",
    "firefox",
    "chrome",
    "chromium",
    "edge",
    "iNetCache".lower(),
    "inetcache",
    "temporary internet files",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_junk_rel(rel: Path) -> bool:
    parts = [p.lower() for p in rel.parts]
    for p in parts:
        if p in JUNK_PARTS:
            return True
        if p.startswith(".") and p not in (".", ".."):
            # hidden tool dirs; keep normal doc folders
            if p in {".svn", ".hg", ".cache", ".npm", ".nuget"}:
                return True
    return False


def fast_fp(p: Path, head: int = 4 * 1024 * 1024) -> str | None:
    """size + mtime + first 4MB — enough for land dedup, not full hash tax."""
    try:
        st = p.stat()
        h = hashlib.sha256()
        h.update(str(st.st_size).encode())
        h.update(str(int(st.st_mtime)).encode())
        with p.open("rb") as f:
            h.update(f.read(head))
        return h.hexdigest()
    except Exception:
        return None


def load_landed_sources(con: sqlite3.Connection) -> set[str]:
    out: set[str] = set()
    try:
        for (sp,) in con.execute(
            "SELECT source_path FROM ingest WHERE process_status='landed_booksbloom_pilot'"
        ):
            if sp:
                out.add(str(sp).replace("/", "\\").lower())
                out.add(str(sp).replace("\\", "/").lower())
    except Exception:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--max-mb", type=float, default=80.0, help="skip huge media this pilot wave")
    ap.add_argument(
        "--include-junk",
        action="store_true",
        help="land AppData/cache trees (default: skip junk for polish)",
    )
    args = ap.parse_args()
    if not SRC.is_dir():
        print(json.dumps({"error": "G:/Booksbloom missing"}))
        return 1

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    now = utc()
    planned: list[tuple[Path, Path, int]] = []
    skipped = 0
    junk_skipped = 0

    con_ro = sqlite3.connect(str(REG), timeout=60)
    try:
        con_ro.execute("PRAGMA busy_timeout=60000")
    except Exception:
        pass
    landed = load_landed_sources(con_ro)
    con_ro.close()

    for p in SRC.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() in SKIP_NAME or p.suffix.lower() in SKIP_EXT:
            skipped += 1
            continue
        try:
            rel = p.relative_to(SRC)
        except Exception:
            rel = Path(p.name)
        if not args.include_junk and is_junk_rel(rel):
            junk_skipped += 1
            continue
        sp_key = str(p).replace("/", "\\").lower()
        sp_key2 = str(p).replace("\\", "/").lower()
        if sp_key in landed or sp_key2 in landed:
            skipped += 1
            continue
        dest = DEST_ROOT / rel
        if dest.is_file():
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
        planned.append((p, dest, sz))
        if len(planned) >= args.limit:
            break

    applied = 0
    errors = 0
    con = None
    if args.apply:
        con = sqlite3.connect(str(REG), timeout=120)
        con.execute("PRAGMA busy_timeout=120000")
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass

    for src, dest, sz in planned:
        if not args.apply:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            sh = fast_fp(dest)
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
            if applied % 50 == 0:
                con.commit()
        except Exception:
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
| Skipped (already) | {skipped} |
| Junk skipped | {junk_skipped} |
| Errors | {errors} |
| Landed set size | {len(landed)} |
| Dest | `{DEST_ROOT}` |
| Rule | **No Inbox** · copy-first · nested origin · junk-skip default |
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
                "junk_skipped": junk_skipped,
                "errors": errors,
                "landed_set": len(landed),
                "dest": str(DEST_ROOT),
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
