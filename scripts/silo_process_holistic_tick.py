#!/usr/bin/env python3
"""Holistic processing streamline tick — repair / re-OCR / enrich / status sync.

Coordinates (does not fight land chef):
  1) OCR cook (process-only when queue deep)
  2) Retire hopeless corrupt after max attempts → DLQ
  3) Backfill registry process_status from sidecars
  4) Clean OCR → .train.md for RAG/twin
  5) Re-queue thin/garbled OCR for re-OCR
  6) Medical/Navy text index

$0 Grok. Fail-soft. Jeff 2026-07-13 holistic streamlining.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state")
OCR_DB = STATE / "ocr_backlog.sqlite3"
REG = STATE / "ingest_registry.sqlite3"
DLQ = STATE / "silo_dead_letter_queue.jsonl"
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-process-holistic-latest.md")
PY = sys.executable
MAX_ATTEMPTS = 4


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 300) -> dict:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(SCRIPTS)
        )
        out = ((r.stdout or "") + (r.stderr or ""))[-1500:]
        return {"exit": r.returncode, "out": out}
    except subprocess.TimeoutExpired:
        return {"exit": 124, "out": "timeout"}
    except Exception as e:
        return {"exit": 1, "out": str(e)[:300]}


def retire_corrupt() -> int:
    if not OCR_DB.is_file():
        return 0
    con = sqlite3.connect(str(OCR_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    rows = con.execute(
        """SELECT path, attempts, status, chars FROM ocr_queue
           WHERE status IN ('needs_ocr','error','empty') AND attempts >= ?
           LIMIT 80""",
        (MAX_ATTEMPTS,),
    ).fetchall()
    n = 0
    for path, attempts, status, chars in rows:
        con.execute(
            "UPDATE ocr_queue SET status='corrupt_retired', updated_at=? WHERE path=?",
            (utc(), path),
        )
        try:
            with DLQ.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "at": utc(),
                            "kind": "ocr_corrupt_retired",
                            "path": path,
                            "attempts": attempts,
                            "prev_status": status,
                            "chars": chars,
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass
        n += 1
    con.commit()
    con.close()
    return n


def requeue_thin_ocr(limit: int = 40) -> int:
    """Re-queue ok_text with very short sidecar or thin chars for re-OCR."""
    if not OCR_DB.is_file():
        return 0
    con = sqlite3.connect(str(OCR_DB), timeout=60)
    rows = con.execute(
        """SELECT path, chars FROM ocr_queue
           WHERE status='ok_text' AND (chars IS NULL OR chars < 120)
           LIMIT ?""",
        (limit,),
    ).fetchall()
    n = 0
    for path, chars in rows:
        p = Path(path)
        ocr = Path(str(p) + ".ocr.md")
        thin = True
        if ocr.is_file() and ocr.stat().st_size > 400:
            thin = False
        if not thin and (chars or 0) >= 120:
            continue
        # medical/navy only for auto requeue
        low = path.lower()
        if not any(k in low for k in ("medical", "navy", "nmcp", "vamc", "ncdoc", "orders")):
            continue
        con.execute(
            """UPDATE ocr_queue SET status='needs_ocr', score=score+30, updated_at=?
               WHERE path=?""",
            (utc(), path),
        )
        n += 1
    con.commit()
    con.close()
    return n


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr-limit", type=int, default=20)
    ap.add_argument("--status-limit", type=int, default=400)
    ap.add_argument("--clean-limit", type=int, default=30)
    ap.add_argument("--skip-ocr", action="store_true")
    args = ap.parse_args()

    report: dict = {"at": utc(), "steps": {}}

    # 1 retire corrupt
    report["steps"]["retire_corrupt"] = retire_corrupt()

    # 1b reacquire missing from source
    report["steps"]["reacquire"] = run(
        [PY, str(SCRIPTS / "silo_reacquire_missing.py"), "--limit", "30"],
        timeout=180,
    )

    # 2 requeue thin medical/navy
    report["steps"]["requeue_thin"] = requeue_thin_ocr(40)

    # 3 OCR process-only
    if not args.skip_ocr:
        report["steps"]["ocr"] = run(
            [
                PY,
                str(SCRIPTS / "silo_ocr_backlog_worker.py"),
                "--limit",
                str(args.ocr_limit),
                "--process-only",
            ],
            timeout=420,
        )

    # 4 process status backfill (prefer unprocessed)
    report["steps"]["process_status"] = run(
        [
            PY,
            str(SCRIPTS / "process_status_batch.py"),
            "--limit",
            str(args.status_limit),
        ],
        timeout=180,
    )
    report["steps"]["ocr_registry_sync"] = run(
        [PY, str(SCRIPTS / "silo_sync_ocr_to_registry.py"), "--limit", str(args.status_limit)],
        timeout=120,
    )

    # 5 text clean → train.md
    clean = SCRIPTS / "silo_ocr_text_clean.py"
    if clean.is_file():
        report["steps"]["text_clean"] = run(
            [PY, str(clean), "--limit", str(args.clean_limit)],
            timeout=240,
        )

    # 6 medical navy index
    mni = SCRIPTS / "silo_medical_navy_text_index.py"
    if mni.is_file():
        report["steps"]["medical_navy_index"] = run(
            [PY, str(mni), "--limit", "40"],
            timeout=120,
        )

    # snapshot counts
    try:
        oc = sqlite3.connect(str(OCR_DB), timeout=30)
        report["ocr"] = dict(
            oc.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status").fetchall()
        )
        oc.close()
    except Exception as e:
        report["ocr"] = {"err": str(e)}
    try:
        rg = sqlite3.connect(str(REG), timeout=30)
        report["process"] = dict(
            rg.execute(
                "SELECT process_status, COUNT(*) FROM ingest GROUP BY process_status"
            ).fetchall()
        )
        rg.close()
    except Exception as e:
        report["process"] = {"err": str(e)}

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Process holistic tick — {report['at'][:19]} UTC",
        "",
        f"- retire_corrupt: **{report['steps'].get('retire_corrupt')}**",
        f"- requeue_thin: **{report['steps'].get('requeue_thin')}**",
        f"- ocr: exit={report['steps'].get('ocr', {}).get('exit')}",
        f"- process_status: exit={report['steps'].get('process_status', {}).get('exit')}",
        f"- text_clean: exit={report['steps'].get('text_clean', {}).get('exit')}",
        f"- medical_navy_index: exit={report['steps'].get('medical_navy_index', {}).get('exit')}",
        "",
        f"OCR: `{report.get('ocr')}`",
        f"Process: `{report.get('process')}`",
        "",
    ]
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str)[:3500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
