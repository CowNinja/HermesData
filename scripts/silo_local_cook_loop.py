#!/usr/bin/env python3
"""Local sovereign cook loop — OCR + train + index WITHOUT cloud tokens.

Post-OCR era (2026-07-14): when OCR open==0, skip OCR worker and spend budget
on train + medical/navy index + twin meta stamp.

Usage:
  python silo_local_cook_loop.py --once
  python silo_local_cook_loop.py --rounds 5 --ocr-limit 20
  python silo_local_cook_loop.py --once --local-llm
  python silo_local_cook_loop.py --once --smoke
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
PY = sys.executable
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-local-cook-latest.md")
STATE = Path(r"D:/HermesData/state/silo_local_cook_state.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout {timeout}s"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def promote_fat_ocr_md() -> int:
    import sqlite3
    from pathlib import Path as P

    con = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=60)
    n = 0
    now = utc()
    for path, st in con.execute(
        "SELECT path, status FROM ocr_queue WHERE status IN ('needs_ocr','empty','error')"
    ).fetchall():
        ocr = P(str(path) + ".ocr.md")
        if ocr.is_file() and ocr.stat().st_size >= 800:
            try:
                body = ocr.read_text(encoding="utf-8", errors="replace")
                chars = len(body.strip())
            except Exception:
                chars = int(ocr.stat().st_size)
            con.execute(
                "UPDATE ocr_queue SET status='ok_text', chars=?, engine=COALESCE(NULLIF(engine,''), 'promote_fat'), updated_at=? WHERE path=?",
                (chars, now, path),
            )
            n += 1
    con.commit()
    con.close()
    return n


def ocr_stats() -> dict:
    import sqlite3

    c = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=30)
    d = dict(c.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
    c.close()
    return d


def ocr_open(stats: dict) -> int:
    return int(stats.get("needs_ocr") or 0) + int(stats.get("queued") or 0) + int(
        stats.get("error") or 0
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--ocr-limit", type=int, default=18)
    ap.add_argument("--train-limit", type=int, default=25)
    ap.add_argument("--index-limit", type=int, default=30)
    ap.add_argument("--stamp-limit", type=int, default=40, help="twin meta stamps per round")
    ap.add_argument("--local-llm", action="store_true", help="optional grunt tag pass")
    ap.add_argument("--sleep", type=int, default=5)
    ap.add_argument(
        "--force-ocr",
        action="store_true",
        help="run OCR worker even when open==0",
    )
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="run silo_twin_readiness_smoke.py after rounds",
    )
    args = ap.parse_args()
    rounds = 1 if args.once else max(1, args.rounds)
    results = []
    for i in range(rounds):
        before = ocr_stats()
        open_n = ocr_open(before)
        # Post-OCR era: skip empty OCR worker; spend budget on twin depth
        if open_n > 0 or args.force_ocr:
            code_ocr, _out_ocr = run(
                [
                    PY,
                    str(SCRIPTS / "silo_ocr_backlog_worker.py"),
                    "--process-only",
                    "--limit",
                    str(args.ocr_limit),
                ],
                timeout=480,
            )
        else:
            code_ocr, _out_ocr = 0, "skipped_ocr_open_0"
        prom = promote_fat_ocr_md()
        train_lim = args.train_limit if open_n > 0 else max(args.train_limit, 35)
        index_lim = args.index_limit if open_n > 0 else max(args.index_limit, 40)
        code_tr, _out_tr = run(
            [
                PY,
                str(SCRIPTS / "batch_train_derivatives.py"),
                "--limit",
                str(train_lim),
                "--timeout",
                "60",
            ],
            timeout=240,
        )
        code_ix, _out_ix = run(
            [
                PY,
                str(SCRIPTS / "silo_medical_navy_text_index.py"),
                "--limit",
                str(index_lim),
            ],
            timeout=120,
        )
        code_st, _out_st = run(
            [
                PY,
                str(SCRIPTS / "silo_twin_meta_stamp.py"),
                "--limit",
                str(args.stamp_limit),
                "--also-navy",
                "--also-family",
                "--max-scan",
                "1200",
            ],
            timeout=120,
        )
        code_cl, _out_cl = run(
            [
                PY,
                str(SCRIPTS / "silo_ocr_text_clean.py"),
                "--limit",
                "15",
                "--domain",
                "Medical",
            ],
            timeout=120,
        )
        llm = None
        if args.local_llm:
            code_h, out_h = run([PY, str(SCRIPTS / "grunt_local.py"), "health"], timeout=30)
            llm = {"health_code": code_h, "health": out_h[-500:]}
        after = ocr_stats()
        wave = {
            "round": i + 1,
            "at": utc(),
            "ocr_open_before": open_n,
            "ocr_code": code_ocr,
            "promoted_fat": prom,
            "train_code": code_tr,
            "index_code": code_ix,
            "stamp_code": code_st,
            "clean_code": code_cl,
            "before": before,
            "after": after,
            "ok_delta": (after.get("ok_text") or 0) - (before.get("ok_text") or 0),
            "queued_delta": (after.get("queued") or 0) - (before.get("queued") or 0),
            "llm": llm,
            "mode": "post_ocr_depth" if open_n == 0 and not args.force_ocr else "ocr_drain",
        }
        results.append(wave)
        print(json.dumps(wave, indent=2))
        if i + 1 < rounds:
            time.sleep(args.sleep)

    STATE.write_text(json.dumps({"at": utc(), "results": results[-5:]}, indent=2), encoding="utf-8")
    lines = [
        f"# Local cook loop — {utc()}",
        "",
        f"**Rounds:** {rounds} · OCR limit {args.ocr_limit} · post-OCR auto-skip when open=0",
        "",
        "| Round | mode | ok_delta | ok_text | open | codes |",
        "|------:|------|---------:|--------:|-----:|-------|",
    ]
    for w in results:
        lines.append(
            f"| {w['round']} | {w.get('mode')} | {w['ok_delta']} | {w['after'].get('ok_text')} | "
            f"{w.get('ocr_open_before')} | o={w['ocr_code']} t={w['train_code']} s={w.get('stamp_code')} |"
        )
    lines += [
        "",
        "Local-only (no Grok tokens). Twin meta stamp + train/index primary when OCR drained.",
        "[[Operations/Twin-Readiness-Post-OCR-CANONICAL-2026-07-14]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], timeout=60)
    if args.smoke:
        run([PY, str(SCRIPTS / "silo_twin_readiness_smoke.py")], timeout=300)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
