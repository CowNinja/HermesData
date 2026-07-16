#!/usr/bin/env python3
"""Overnight full-tilt silo cook — OCR + train/index + Booksbloom pilot.

Designed for multi-hour unattended runs (Jeff sleep window).
Local-only; no cloud tokens.

Usage:
  python silo_overnight_cook.py --hours 9
  python silo_overnight_cook.py --hours 9 --bb-limit 300 --ocr-limit 20
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
PY = sys.executable
STATE = Path(r"D:/HermesData/state/silo_overnight_cook_state.json")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-overnight-cook-latest.md")
LOG = Path(r"D:/HermesData/state/silo_overnight_cook.log")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    line = f"{utc()} {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(args: list[str], timeout: int) -> tuple[int, str]:
    try:
        r = subprocess.run(
            args,
            cwd=str(SCRIPTS),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-3000:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def ocr_stats() -> dict:
    c = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=60)
    d = dict(c.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
    c.close()
    return d


def bb_count() -> int:
    c = sqlite3.connect(r"D:/HermesData/state/ingest_registry.sqlite3", timeout=60)
    n = c.execute(
        "SELECT COUNT(*) FROM ingest WHERE process_status='landed_booksbloom_pilot'"
    ).fetchone()[0]
    c.close()
    return int(n)


def cycle(ocr_limit: int, train_limit: int, index_limit: int, bb_limit: int) -> dict:
    before = ocr_stats()
    # repoint dead paths occasionally
    run([PY, str(SCRIPTS / "silo_ocr_queue_repoint.py")], timeout=180)
    code_o, _ = run(
        [
            PY,
            str(SCRIPTS / "silo_ocr_backlog_worker.py"),
            "--process-only",
            "--limit",
            str(ocr_limit),
        ],
        timeout=480,
    )
    # promote fat ocr.md (chars + status — hang-fix for stuck gold tail)
    try:
        con = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=60)
        now = utc()
        prom = 0
        for path, st in con.execute(
            "SELECT path, status FROM ocr_queue WHERE status IN ('needs_ocr','empty','error')"
        ):
            o = Path(str(path) + ".ocr.md")
            if o.is_file() and o.stat().st_size >= 800:
                try:
                    chars = len(o.read_text(encoding="utf-8", errors="replace").strip())
                except Exception:
                    chars = int(o.stat().st_size)
                con.execute(
                    "UPDATE ocr_queue SET status='ok_text', chars=?, engine=COALESCE(NULLIF(engine,''), 'promote_fat'), updated_at=? WHERE path=?",
                    (chars, now, path),
                )
                prom += 1
        con.commit()
        con.close()
    except Exception:
        prom = -1
    code_t, _ = run(
        [PY, str(SCRIPTS / "batch_train_derivatives.py"), "--limit", str(train_limit)],
        timeout=180,
    )
    code_i, _ = run(
        [
            PY,
            str(SCRIPTS / "silo_medical_navy_text_index.py"),
            "--limit",
            str(index_limit),
        ],
        timeout=120,
    )
    # Post-OCR twin meta stamp (bounded — never hang rglob)
    code_st, _ = run(
        [
            PY,
            str(SCRIPTS / "silo_twin_meta_stamp.py"),
            "--limit",
            "40",
            "--also-navy",
            "--also-family",
            "--max-scan",
            "800",
        ],
        timeout=120,
    )
    code_b, out_b = run(
        [
            PY,
            str(SCRIPTS / "silo_booksbloom_pilot_land.py"),
            "--apply",
            "--limit",
            str(bb_limit),
        ],
        timeout=300,
    )
    run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], timeout=60)
    after = ocr_stats()
    return {
        "at": utc(),
        "ocr_code": code_o,
        "train_code": code_t,
        "index_code": code_i,
        "stamp_code": code_st,
        "bb_code": code_b,
        "promoted": prom,
        "before": before,
        "after": after,
        "ok_delta": after.get("ok_text", 0) - before.get("ok_text", 0),
        "queued": after.get("queued"),
        "bb_total": bb_count(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=9.0)
    ap.add_argument("--ocr-limit", type=int, default=20)
    ap.add_argument("--train-limit", type=int, default=25)
    ap.add_argument("--index-limit", type=int, default=30)
    ap.add_argument("--bb-limit", type=int, default=250)
    ap.add_argument("--sleep", type=int, default=8, help="seconds between cycles")
    args = ap.parse_args()
    deadline = time.time() + args.hours * 3600
    cycles = []
    log(f"OVERNIGHT START hours={args.hours}")
    n = 0
    while time.time() < deadline:
        n += 1
        try:
            w = cycle(args.ocr_limit, args.train_limit, args.index_limit, args.bb_limit)
            cycles.append(w)
            log(
                f"cycle={n} ok_delta={w['ok_delta']} ok_text={w['after'].get('ok_text')} "
                f"queued={w['queued']} bb={w['bb_total']} ocr_code={w['ocr_code']}"
            )
            STATE.write_text(
                json.dumps(
                    {
                        "at": utc(),
                        "cycles": n,
                        "last": w,
                        "hours_target": args.hours,
                        "deadline_left_s": max(0, int(deadline - time.time())),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            RECEIPT.parent.mkdir(parents=True, exist_ok=True)
            RECEIPT.write_text(
                f"""# Overnight cook — {utc()}

**Cycles:** {n} · target hours {args.hours}

| Metric | Value |
|--------|------:|
| ok_text | {w['after'].get('ok_text')} |
| queued | {w['queued']} |
| bb pilot | {w['bb_total']} |
| last ok_delta | {w['ok_delta']} |

Log: `{LOG}`
""",
                encoding="utf-8",
            )
        except Exception as e:
            log(f"cycle_error {type(e).__name__}: {e}")
        # stop early if queue empty and bb planned 0 repeatedly
        if cycles and cycles[-1].get("queued", 1) == 0 and n > 3:
            log("queue empty — continue bb/train until deadline")
        time.sleep(args.sleep)
    log(f"OVERNIGHT END cycles={n}")
    print(json.dumps({"cycles": n, "last": cycles[-1] if cycles else None}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
