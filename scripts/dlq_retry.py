#!/usr/bin/env python3
"""Retry open drain DLQ items once (bounded). Success → status closed."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from drain_dlq import DB, connect, write_receipt  # noqa: E402

try:
    from ingest_registry import connect as reg_connect, register, sha256_file
except Exception:
    reg_connect = None
    register = None
    sha256_file = None


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    con = connect()
    rows = con.execute(
        "SELECT * FROM dlq WHERE status='open' AND attempts < 5 ORDER BY attempts ASC LIMIT ?",
        (args.limit,),
    ).fetchall()
    ok = fail = 0
    for r in rows:
        src = Path(r["source_path"])
        dest = Path(r["dest_path"] or "")
        if not src.is_file():
            con.execute(
                "UPDATE dlq SET status='closed_source_gone', last_seen=? WHERE id=?",
                (utc(), r["id"]),
            )
            ok += 1
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(src, dest)
            dig = sha256_file(src) if sha256_file else ""
            if reg_connect and register:
                icon = reg_connect()
                register(icon, str(src), str(dest), digest=dig, size=src.stat().st_size, status="copied")
                icon.commit()
            con.execute(
                "UPDATE dlq SET status='closed_ok', last_seen=?, attempts=attempts+1 WHERE id=?",
                (utc(), r["id"]),
            )
            ok += 1
        except Exception as e:
            con.execute(
                "UPDATE dlq SET attempts=attempts+1, last_seen=?, error=? WHERE id=?",
                (utc(), str(e)[:500], r["id"]),
            )
            fail += 1
    con.commit()
    con.close()
    write_receipt()
    print(json.dumps({"retried": len(rows), "ok": ok, "fail": fail}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
