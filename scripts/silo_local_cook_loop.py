#!/usr/bin/env python3
"""Local sovereign cook loop — OCR + train + index WITHOUT cloud tokens.

Runs mechanical factory steps on-box. Optional Qwythos grunt for tag enrich
via grunt_local when --local-llm.

Usage:
  python silo_local_cook_loop.py --once
  python silo_local_cook_loop.py --rounds 5 --ocr-limit 20
  python silo_local_cook_loop.py --once --local-llm   # uses :8091 classify on samples

Grok/Hermes should prefer this over in-chat OCR waves.
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
    except subprocess.TimeoutExpired as e:
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
        "SELECT path, status FROM ocr_queue WHERE status IN ('needs_ocr','empty')"
    ).fetchall():
        ocr = P(str(path) + ".ocr.md")
        if ocr.is_file() and ocr.stat().st_size >= 800:
            con.execute(
                "UPDATE ocr_queue SET status='ok_text', updated_at=? WHERE path=?",
                (now, path),
            )
            n += 1
    con.commit()
    return n


def ocr_stats() -> dict:
    import sqlite3

    c = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=30)
    d = dict(c.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
    c.close()
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--ocr-limit", type=int, default=18)
    ap.add_argument("--train-limit", type=int, default=25)
    ap.add_argument("--index-limit", type=int, default=30)
    ap.add_argument("--local-llm", action="store_true", help="optional grunt tag pass")
    ap.add_argument("--sleep", type=int, default=5)
    args = ap.parse_args()
    rounds = 1 if args.once else max(1, args.rounds)
    results = []
    for i in range(rounds):
        before = ocr_stats()
        code_ocr, out_ocr = run(
            [
                PY,
                str(SCRIPTS / "silo_ocr_backlog_worker.py"),
                "--process-only",
                "--limit",
                str(args.ocr_limit),
            ],
            timeout=480,
        )
        prom = promote_fat_ocr_md()
        code_tr, out_tr = run(
            [
                PY,
                str(SCRIPTS / "batch_train_derivatives.py"),
                "--limit",
                str(args.train_limit),
            ],
            timeout=180,
        )
        code_ix, out_ix = run(
            [
                PY,
                str(SCRIPTS / "silo_medical_navy_text_index.py"),
                "--limit",
                str(args.index_limit),
            ],
            timeout=120,
        )
        code_cl, out_cl = run(
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
            code_h, out_h = run(
                [PY, str(SCRIPTS / "grunt_local.py"), "health"], timeout=30
            )
            llm = {"health_code": code_h, "health": out_h[-500:]}
        after = ocr_stats()
        wave = {
            "round": i + 1,
            "at": utc(),
            "ocr_code": code_ocr,
            "train_code": code_tr,
            "index_code": code_ix,
            "clean_code": code_cl,
            "before": before,
            "after": after,
            "ok_delta": after.get("ok_text", 0) - before.get("ok_text", 0),
            "queued_delta": after.get("queued", 0) - before.get("queued", 0),
            "llm": llm,
        }
        results.append(wave)
        print(json.dumps(wave, indent=2))
        if i + 1 < rounds:
            time.sleep(args.sleep)

    STATE.write_text(json.dumps({"at": utc(), "results": results[-5:]}, indent=2), encoding="utf-8")
    lines = [
        f"# Local cook loop — {utc()}",
        "",
        f"**Rounds:** {rounds} · OCR limit {args.ocr_limit}",
        "",
        "| Round | ok_delta | ok_text | queued | codes |",
        "|------:|---------:|--------:|-------:|-------|",
    ]
    for w in results:
        lines.append(
            f"| {w['round']} | {w['ok_delta']} | {w['after'].get('ok_text')} | "
            f"{w['after'].get('queued')} | o={w['ocr_code']} t={w['train_code']} |"
        )
    lines += [
        "",
        "Local-only (no Grok tokens). Grunt/Qwythos optional via `--local-llm`.",
        "[[Operations/Silo-Local-Cook-Offload-CANONICAL-2026-07-13]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], timeout=60)
    print(json.dumps({"rounds": rounds, "receipt": str(RECEIPT), "last": results[-1]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
