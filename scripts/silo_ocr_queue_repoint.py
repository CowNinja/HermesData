#!/usr/bin/env python3
"""Repoint OCR queue rows whose path died after rehome (Inbox→shelf).

Matches basename via ingest registry; sets resolved_dup if shelf path already queued.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

OCR = Path(r"D:/HermesData/state/ocr_backlog.sqlite3")
REG = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-ocr-queue-repoint-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    now = utc()
    ocr = sqlite3.connect(str(OCR), timeout=120)
    reg = sqlite3.connect(str(REG), timeout=120)
    fixed = 0
    rows = ocr.execute(
        "SELECT path, status FROM ocr_queue WHERE status IN ('queued','needs_ocr','missing')"
    ).fetchall()
    for path, st in rows:
        if Path(path).is_file():
            continue
        name = Path(path).name
        alt = reg.execute(
            "SELECT dest_path FROM ingest WHERE dest_path LIKE ? "
            "AND domain NOT LIKE '%Inbox%' AND dest_path IS NOT NULL LIMIT 8",
            (f"%{name}%",),
        ).fetchall()
        live = None
        for (d,) in alt:
            if d and Path(d).is_file() and Path(d).name.lower() == name.lower():
                live = d
                break
        if not live:
            ocr.execute(
                "UPDATE ocr_queue SET status='missing', updated_at=? WHERE path=?",
                (now, path),
            )
            continue
        if ocr.execute("SELECT 1 FROM ocr_queue WHERE path=?", (live,)).fetchone():
            ocr.execute(
                "UPDATE ocr_queue SET status='resolved_dup', updated_at=? WHERE path=?",
                (now, path),
            )
        else:
            ocr.execute(
                "UPDATE ocr_queue SET path=?, status='queued', updated_at=? WHERE path=?",
                (live, now, path),
            )
        fixed += 1
    ocr.commit()
    stats = dict(ocr.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"# OCR queue repoint — {now}\n\n**Repointed/dup:** {fixed}\n\n{stats}\n",
        encoding="utf-8",
    )
    print(json.dumps({"fixed": fixed, "stats": stats, "receipt": str(RECEIPT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
