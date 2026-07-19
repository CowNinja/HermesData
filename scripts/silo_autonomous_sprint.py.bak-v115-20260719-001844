#!/usr/bin/env python3
"""Fully autonomous silo sprint — 100% local, zero Grok tokens.

One entrypoint for unattended post-OCR twin depth + health + gates.

Usage:
  python silo_autonomous_sprint.py --once
  python silo_autonomous_sprint.py --hours 4 --sleep 20
  python silo_autonomous_sprint.py --once --smoke
  python silo_autonomous_sprint.py --self-heal-only

Does NOT purge. Does NOT unpark products. Does NOT land next sources without
--land-next (still copy-only dry/apply with rules; default off).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Detach console immediately so hidden python.exe never steals focus while typing.
try:
    from win_free_console import free_console  # type: ignore

    free_console()
except Exception:
    try:
        import ctypes

        if sys.platform == "win32":
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

SCRIPTS = Path(r"D:/HermesData/scripts")
# Prefer python.exe (not pythonw) for stable child subprocess pipes; FreeConsole hides it.
_py = Path(sys.executable)
if _py.name.lower() == "pythonw.exe":
    _alt = _py.with_name("python.exe")
    PY = str(_alt) if _alt.is_file() else sys.executable
else:
    PY = sys.executable
STATE = Path(r"D:/HermesData/state/silo_autonomous_sprint_state.json")
LOG = Path(r"D:/HermesData/state/silo_autonomous_sprint.log")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-autonomous-sprint-latest.md")
STOP = Path(r"D:/HermesData/state/silo_autonomous.STOP")


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
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        r = subprocess.run(
            args,
            cwd=str(SCRIPTS),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=flags if sys.platform == "win32" else 0,
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-2500:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def port_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def ocr_open() -> int:
    try:
        c = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=30)
        d = dict(c.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
        c.close()
        return int(d.get("needs_ocr") or 0) + int(d.get("queued") or 0) + int(
            d.get("error") or 0
        )
    except Exception:
        return -1


def self_heal() -> dict:
    """Detect and fix common flakes without human/Grok."""
    fixes = []
    code, out = run([PY, str(SCRIPTS / "silo_ocr_tail_hard.py")], 120)
    fixes.append({"ocr_tail_hard": code, "tail": out[-120:]})
    code, out = run([PY, str(SCRIPTS / "silo_ocr_queue_repoint.py")], 120)
    fixes.append({"repoint": code})
    q = port_ok("http://127.0.0.1:8090/health")
    p = port_ok("http://127.0.0.1:8091/health")
    fixes.append({"qwythos": q, "proxy": p})
    return {"at": utc(), "fixes": fixes, "ocr_open": ocr_open()}


def depth_cycle(stamp_limit: int, index_limit: int, train_limit: int) -> dict:
    """Lightweight post-OCR depth — no nested cook (avoids multi-hour hangs)."""
    open_n = ocr_open()
    codes = {}
    # OCR only if open work remains
    if open_n > 0:
        codes["ocr"], _ = run(
            [
                PY,
                str(SCRIPTS / "silo_ocr_backlog_worker.py"),
                "--process-only",
                "--limit",
                "12",
            ],
            240,
        )
        run([PY, str(SCRIPTS / "silo_ocr_tail_hard.py")], 90)
    else:
        codes["ocr"] = 0
    # train (OCR-queue + registry-recent HTML; rotate shelves — 2026-07-18)
    train_roots = [
        r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Family",
        r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Medical-Records",
        r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Navy-Service",
        r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Life-Archive",
        r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/_Inbox",
        r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Friends",
    ]
    train_root = train_roots[int(time.time() // 60) % len(train_roots)]
    codes["train"], out_tr = run(
        [
            PY,
            str(SCRIPTS / "batch_train_derivatives.py"),
            "--root",
            train_root,
            "--limit",
            str(min(train_limit, 20)),
            "--timeout",
            "40",
            "--max-scan",
            "2000",
        ],
        150,
    )
    # index
    codes["index"], _ = run(
        [
            PY,
            str(SCRIPTS / "silo_medical_navy_text_index.py"),
            "--limit",
            str(index_limit),
        ],
        90,
    )
    # rotating stamp shelf
    shelves = [
        (r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Medical-Records", 35, 600),
        (r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Navy-Service", 30, 350),
        (r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Family", 30, 350),
        (r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Projects", 35, 400),
    ]
    root, lim, scan = shelves[int(time.time() // 60) % len(shelves)]
    codes["stamp"], out_st = run(
        [
            PY,
            str(SCRIPTS / "silo_twin_meta_stamp.py"),
            "--root",
            root,
            "--limit",
            str(min(stamp_limit, lim)),
            "--max-scan",
            str(scan),
        ],
        100,
    )
    stamps = [{"root": Path(root).name, "code": codes["stamp"], "out": out_st.strip()[-160:]}]
    # booksbloom residual
    codes["bb"], out_bb = run(
        [PY, str(SCRIPTS / "silo_booksbloom_pilot_land.py"), "--apply", "--limit", "100"],
        90,
    )
    # observability bundle
    run([PY, str(SCRIPTS / "silo_scoreboard_pulse.py")], 40)
    run([PY, str(SCRIPTS / "silo_purge_plan_report.py")], 40)
    run([PY, str(SCRIPTS / "silo_next_sources_pipeline.py")], 50)
    run([PY, str(SCRIPTS / "silo_twin_retrieval_cache.py")], 75)
    run([PY, str(SCRIPTS / "silo_future_projects_parking.py"), "readiness"], 120)
    return {
        "at": utc(),
        "ocr_open": open_n,
        "cook_code": codes.get("train", 0),  # compat field
        "codes": codes,
        "stamps": stamps,
        "bb_code": codes.get("bb"),
        "bb_out": out_bb.strip()[-160:],
        "train_tail": out_tr.strip()[-120:],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--hours", type=float, default=0, help="run until deadline; 0 with --once only")
    ap.add_argument("--sleep", type=int, default=25)
    ap.add_argument("--stamp-limit", type=int, default=35)
    ap.add_argument("--index-limit", type=int, default=40)
    ap.add_argument("--train-limit", type=int, default=25)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--self-heal-only", action="store_true")
    args = ap.parse_args()

    if STOP.is_file():
        log("STOP present — exit")
        print(json.dumps({"stopped": True, "path": str(STOP)}))
        return 0

    if args.self_heal_only:
        heal = self_heal()
        print(json.dumps(heal, indent=2))
        return 0

    deadline = None
    if args.hours and args.hours > 0:
        deadline = datetime.now(timezone.utc) + timedelta(hours=args.hours)
    cycles = []
    n = 0
    while True:
        if STOP.is_file():
            log("STOP seen mid-run")
            break
        n += 1
        log(f"cycle {n} start")
        heal = self_heal()
        depth = depth_cycle(args.stamp_limit, args.index_limit, args.train_limit)
        # every 4th cycle: vault gardener daily (light)
        if n % 4 == 0:
            run([PY, str(SCRIPTS / "vault_gardener_autonomy_suite.py"), "--mode", "daily"], 180)
        if args.smoke or n == 1:
            sc, so = run([PY, str(SCRIPTS / "silo_twin_readiness_smoke.py")], 300)
            smoke = {"code": sc, "out": so.strip()[-200:]}
        else:
            smoke = None
        rec = {"cycle": n, "heal": heal, "depth": depth, "smoke": smoke}
        cycles.append(rec)
        STATE.write_text(
            json.dumps(
                {
                    "at": utc(),
                    "cycles": cycles[-8:],
                    "deadline": deadline.isoformat() if deadline else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"cycle {n} done ocr_open={heal.get('ocr_open')} cook={depth.get('cook_code')} train_tail={(depth.get('train_tail') or '')[:80]}")
        if args.once or not deadline:
            break
        if datetime.now(timezone.utc) >= deadline:
            break
        time.sleep(max(5, args.sleep))

    # receipt
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Autonomous silo sprint — {utc()}",
        "",
        f"Cycles: **{len(cycles)}** · STOP={STOP.exists()}",
        "",
        "| Cycle | ocr_open | cook | bb |",
        "|------:|---------:|-----:|---:|",
    ]
    for c in cycles[-12:]:
        d = c.get("depth") or {}
        lines.append(
            f"| {c.get('cycle')} | {d.get('ocr_open')} | {d.get('cook_code')} | {d.get('bb_code')} |"
        )
    lines += [
        "",
        "100% local · zero Grok · purge NOT armed · next-sources not auto-landed",
        "[[Operations/Autonomous-Silo-Runbook-CANONICAL-2026-07-14]]",
    ]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"cycles": len(cycles), "receipt": str(RECEIPT), "state": str(STATE)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
