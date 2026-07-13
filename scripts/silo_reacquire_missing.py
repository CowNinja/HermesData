#!/usr/bin/env python3
"""Re-acquire missing silo files from original source_path when still available.

OCR marks status=missing when dest gone. If ingest registry has source_path
and file still exists on G:, re-copy to dest (or register new dest) and
re-queue OCR. Fail-soft. Does not delete sources.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

OCR_DB = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-reacquire-missing-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not OCR_DB.is_file() or not REG.is_file():
        print(json.dumps({"error": "missing db"}))
        return 2

    oc = sqlite3.connect(str(OCR_DB), timeout=60)
    oc.execute("PRAGMA busy_timeout=60000")
    missing = oc.execute(
        "SELECT path FROM ocr_queue WHERE status='missing' LIMIT ?",
        (args.limit * 3,),
    ).fetchall()

    rg = sqlite3.connect(str(REG), timeout=60)
    rg.execute("PRAGMA busy_timeout=60000")

    results = []
    for (dest_path,) in missing:
        if len(results) >= args.limit:
            break
        dest = Path(dest_path)
        if dest.is_file():
            # already back — requeue OCR
            if not args.dry_run:
                oc.execute(
                    "UPDATE ocr_queue SET status='queued', score=score+10, updated_at=? WHERE path=?",
                    (utc(), dest_path),
                )
            results.append({"path": dest.name, "action": "requeue_exists"})
            continue
        # find source via registry
        row = rg.execute(
            "SELECT source_path, dest_path FROM ingest WHERE dest_path=? OR dest_path LIKE ? LIMIT 1",
            (dest_path, "%" + dest.name),
        ).fetchone()
        if not row:
            results.append({"path": dest.name, "action": "no_registry"})
            continue
        src_s, dest_s = row[0], row[1]
        src = Path(src_s) if src_s else None
        if not src or not src.is_file():
            results.append({"path": dest.name, "action": "source_gone", "src": src_s})
            continue
        target = Path(dest_s) if dest_s else dest
        if args.dry_run:
            results.append({"path": dest.name, "action": "would_copy", "src": src_s})
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                shutil.copy2(src, target)
            # Re-queue under original key if same file; avoid UNIQUE path collisions
            key = dest_path if dest_path else str(target)
            if Path(key).is_file() or target.is_file():
                use_path = str(target) if target.is_file() else key
                # if target path differs and already in queue, just mark that row queued
                if use_path != dest_path:
                    exists = oc.execute(
                        "SELECT 1 FROM ocr_queue WHERE path=?", (use_path,)
                    ).fetchone()
                    if exists:
                        oc.execute(
                            "UPDATE ocr_queue SET status='queued', score=score+20, updated_at=? WHERE path=?",
                            (utc(), use_path),
                        )
                        oc.execute(
                            "UPDATE ocr_queue SET status='resolved_dup', updated_at=? WHERE path=?",
                            (utc(), dest_path),
                        )
                    else:
                        oc.execute(
                            "UPDATE ocr_queue SET path=?, status='queued', score=score+20, updated_at=? WHERE path=?",
                            (use_path, utc(), dest_path),
                        )
                else:
                    oc.execute(
                        "UPDATE ocr_queue SET status='queued', score=score+20, updated_at=? WHERE path=?",
                        (utc(), dest_path),
                    )
            results.append({"path": target.name, "action": "reacquired"})
        except Exception as e:
            results.append({"path": dest.name, "action": "copy_fail", "err": str(e)[:120]})

    if not args.dry_run:
        oc.commit()
    oc.close()
    rg.close()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"# Reacquire missing — {utc()}\n\n"
        + "\n".join(f"- {r}" for r in results)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "processed": len(results),
                "reacquired": sum(1 for r in results if r.get("action") == "reacquired"),
                "requeue_exists": sum(1 for r in results if r.get("action") == "requeue_exists"),
                "results": results[:20],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
