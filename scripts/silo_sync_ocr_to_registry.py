#!/usr/bin/env python3
"""Sync OCR ok_text outcomes into ingest_registry process_status.

Closes the loop: land → OCR → registry shelf label (extracted).
Also marks corrupt_retired / missing for visibility.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

OCR = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    if not OCR.is_file() or not REG.is_file():
        print(json.dumps({"error": "db missing"}))
        return 2

    oc = sqlite3.connect(str(OCR), timeout=60)
    rg = sqlite3.connect(str(REG), timeout=60)
    for db in (oc, rg):
        try:
            db.execute("PRAGMA busy_timeout=60000")
        except Exception:
            pass

    # map ocr status → process_status
    mapping = {
        "ok_text": "extracted",
        "needs_ocr": "ocr_queued",
        "queued": "ocr_queued",
        "corrupt_retired": "ocr_failed",
        "error": "ocr_queued",
        "missing": "missing_dest",
    }
    updated = 0
    for ostatus, pstatus in mapping.items():
        rows = oc.execute(
            "SELECT path FROM ocr_queue WHERE status=? LIMIT ?",
            (ostatus, args.limit),
        ).fetchall()
        for (path,) in rows:
            # match dest_path exact or basename-ish
            cur = rg.execute(
                "SELECT rowid, process_status FROM ingest WHERE dest_path=? LIMIT 1",
                (path,),
            ).fetchone()
            if not cur:
                name = Path(path).name
                cur = rg.execute(
                    "SELECT rowid, process_status FROM ingest WHERE dest_path LIKE ? LIMIT 1",
                    ("%" + name,),
                ).fetchone()
            if not cur:
                continue
            rowid, old = cur
            if old == pstatus or (
                pstatus == "extracted"
                and old in ("derivative_ok", "context_enriched", "extracted")
            ):
                continue
            if old == "derivative_ok":
                continue  # don't downgrade
            rg.execute(
                "UPDATE ingest SET process_status=? WHERE rowid=?",
                (pstatus, rowid),
            )
            updated += 1
            if updated >= args.limit:
                break
        if updated >= args.limit:
            break
    rg.commit()
    by = dict(
        rg.execute(
            "SELECT process_status, COUNT(*) FROM ingest GROUP BY process_status"
        ).fetchall()
    )
    oc.close()
    rg.close()
    print(json.dumps({"updated": updated, "by_process": by, "at": utc()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
