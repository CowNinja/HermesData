#!/usr/bin/env python3
"""Mark process_status on registry rows from sidecar presence.

Statuses:
  unprocessed | extracted | context_enriched | ocr_queued | derivative_ok
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    if not DB.is_file():
        print("no db")
        return 2
    con = sqlite3.connect(str(DB), timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    con.row_factory = sqlite3.Row
    # discover columns
    cols = [r[1] for r in con.execute("PRAGMA table_info(ingest)").fetchall()]
    if "process_status" not in cols:
        try:
            con.execute("ALTER TABLE ingest ADD COLUMN process_status TEXT DEFAULT 'unprocessed'")
            con.commit()
        except Exception as e:
            print("alter fail", e)
    rows = con.execute(
        """SELECT rowid, dest_path, process_status FROM ingest
           WHERE dest_path IS NOT NULL
           ORDER BY CASE WHEN process_status IS NULL OR process_status='unprocessed' THEN 0 ELSE 1 END
           LIMIT ?""",
        (args.limit * 8,),
    ).fetchall()
    updated = 0
    scanned = 0
    for r in rows:
        dest = r["dest_path"] if "dest_path" in r.keys() else r[1]
        if not dest:
            continue
        p = Path(dest)
        if not p.is_file():
            # try as-is
            continue
        scanned += 1
        status = "unprocessed"
        if Path(str(p) + ".train.md").is_file() or Path(str(p) + ".context.train.md").is_file():
            status = "derivative_ok"
        elif Path(str(p) + ".context.json").is_file():
            status = "context_enriched"
        elif Path(str(p) + ".needs_ocr").is_file():
            status = "ocr_queued"
        elif Path(str(p) + ".ocr.md").is_file():
            status = "extracted"
        elif p.suffix.lower() in {".txt", ".md", ".csv", ".json"} and p.stat().st_size > 0:
            status = "extracted"
        cur = r["process_status"] if "process_status" in r.keys() else None
        if cur != status:
            con.execute(
                "UPDATE ingest SET process_status=? WHERE rowid=?",
                (status, r["rowid"] if "rowid" in r.keys() else r[0]),
            )
            updated += 1
        if updated >= args.limit and scanned > args.limit:
            break
    con.commit()
    # counts
    try:
        counts = con.execute(
            "SELECT process_status, COUNT(*) c FROM ingest GROUP BY process_status"
        ).fetchall()
        by = {row[0]: row[1] for row in counts}
    except Exception:
        by = {}
    con.close()
    print({"scanned": scanned, "updated": updated, "by_process": by})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
