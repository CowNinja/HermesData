#!/usr/bin/env python3
"""Mark process_status on registry rows from sidecar presence.

Statuses:
  unprocessed | extracted | context_enriched | ocr_queued | derivative_ok | ghost_cleared

2026-07-26: honor .ocr.md / .stt.md twins; mark missing dest as ghost_cleared
so unprocessed counters and html_thin pick stop thrashing missing Takeout paths.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument(
        "--prefer-twins",
        action="store_true",
        help="Bias gold silo roots first for twin promote",
    )
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
    cols = [r[1] for r in con.execute("PRAGMA table_info(ingest)").fetchall()]
    if "process_status" not in cols:
        try:
            con.execute(
                "ALTER TABLE ingest ADD COLUMN process_status TEXT DEFAULT 'unprocessed'"
            )
            con.commit()
        except Exception as e:
            print("alter fail", e)
    order = """ORDER BY CASE WHEN process_status IS NULL OR process_status='unprocessed' THEN 0 ELSE 1 END"""
    if args.prefer_twins:
        order = """ORDER BY
          CASE
            WHEN lower(dest_path) LIKE '%medical-records%' THEN 0
            WHEN lower(dest_path) LIKE '%navy-service%' THEN 1
            WHEN lower(dest_path) LIKE '%core-personal%' THEN 2
            WHEN lower(dest_path) LIKE '%finance%' THEN 3
            ELSE 8
          END,
          CASE WHEN process_status IS NULL OR process_status='unprocessed' THEN 0 ELSE 1 END
        """
    rows = con.execute(
        f"""SELECT rowid, dest_path, process_status FROM ingest
           WHERE dest_path IS NOT NULL
           {order}
           LIMIT ?""",
        (args.limit * 12,),
    ).fetchall()
    updated = 0
    scanned = 0
    ghosts = 0
    derivatives = 0
    for r in rows:
        dest = r["dest_path"] if "dest_path" in r.keys() else r[1]
        if not dest:
            continue
        p = Path(dest)
        rid = r["rowid"] if "rowid" in r.keys() else r[0]
        cur = r["process_status"] if "process_status" in r.keys() else None
        if not p.is_file():
            if cur != "ghost_cleared":
                con.execute(
                    "UPDATE ingest SET process_status=? WHERE rowid=?",
                    ("ghost_cleared", rid),
                )
                updated += 1
                ghosts += 1
            scanned += 1
            if updated >= args.limit:
                break
            continue
        scanned += 1
        status = "unprocessed"
        train = Path(str(p) + ".train.md")
        stt = Path(str(p) + ".stt.md")
        ocr = Path(str(p) + ".ocr.md")
        ctx_train = Path(str(p) + ".context.train.md")
        if (
            (train.is_file() and train.stat().st_size >= 40)
            or (ctx_train.is_file() and ctx_train.stat().st_size >= 40)
            or (stt.is_file() and stt.stat().st_size >= 40)
        ):
            status = "derivative_ok"
        elif Path(str(p) + ".context.json").is_file():
            status = "context_enriched"
        elif Path(str(p) + ".needs_ocr").is_file():
            status = "ocr_queued"
        elif ocr.is_file() and ocr.stat().st_size >= 40:
            status = "extracted"
        elif p.suffix.lower() in {
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".html",
            ".htm",
            ".eml",
            ".rtf",
        } and p.stat().st_size > 0:
            status = "extracted"
        if cur != status:
            con.execute(
                "UPDATE ingest SET process_status=? WHERE rowid=?",
                (status, rid),
            )
            updated += 1
            if status == "derivative_ok":
                derivatives += 1
        if updated >= args.limit and scanned > args.limit:
            break
    con.commit()
    try:
        counts = con.execute(
            "SELECT process_status, COUNT(*) c FROM ingest GROUP BY process_status"
        ).fetchall()
        by = {row[0]: row[1] for row in counts}
    except Exception:
        by = {}
    con.close()
    print(
        {
            "scanned": scanned,
            "updated": updated,
            "ghosts": ghosts,
            "derivatives": derivatives,
            "by_process": by,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
