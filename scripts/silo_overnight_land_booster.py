#!/usr/bin/env python3
"""Overnight land booster — single-writer gold waves for Jeff sleep cook.

Runs up to --hours. Only starts a drain if no land writers are active
(continuous/orch/focus/drain). Prefer continuous as primary; this is a
fallback when continuous is idle between ticks.

Never purges. Never starts second continuous. Never touches gateway.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
STATE = Path(r"D:/HermesData/state")
LOG = STATE / "silo_overnight_land_booster.log"
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-overnight-land-booster-latest.md")
PY = r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
STOP = STATE / "silo_continuous.STOP"

GOLD = [
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/Google_Backups",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/MyPhoneExplorer_Folders",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/MyPhoneExplorer",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/2019-06-06 - 8GB sdcard 001",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/FaceBook",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/2019-10-09_Razer_Phone2",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/samsung",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/2019-09-21_LEX850",
    r"G:/MemoryCard_Backups/Bloom_Jeffrey/2020-04-22_TeraCube",
]

LAND_MARKERS = (
    "silo_continuous_loop.py",
    "silo_orchestrator_tick.py",
    "silo_focus_land.py",
    "g_to_k_safe_drain.py",
    "g_to_k_drain_autonomous.py",
)


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


def proc_cmdlines() -> str:
    try:
        r = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe' or name='pythonw.exe'",
                "get",
                "CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.stdout or ""
    except Exception as e:
        return f"ERR {e}"


def land_busy() -> dict:
    text = proc_cmdlines().lower()
    counts = {m: text.count(m.lower()) for m in LAND_MARKERS}
    counts["busy"] = sum(1 for m in ("silo_focus_land.py", "g_to_k_safe_drain.py", "g_to_k_drain_autonomous.py") if counts.get(m, 0) > 0)
    counts["continuous"] = counts.get("silo_continuous_loop.py", 0)
    return counts


def run_wave(source: str, limit: int) -> dict:
    r = subprocess.run(
        [PY, str(SCRIPTS / "g_to_k_safe_drain.py"), "--apply", "--limit", str(limit), "--source", source],
        capture_output=True,
        text=True,
        timeout=7200,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    planned = copied = None
    try:
        # last JSON object
        m = re.findall(r"\{[^{}]*\"planned\"[^{}]*\}", out)
        if m:
            j = json.loads(m[-1])
            planned = j.get("planned")
            copied = j.get("copied")
    except Exception:
        pass
    return {"code": r.returncode, "planned": planned, "copied": copied, "tail": out[-400:]}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--sleep", type=int, default=90)
    ap.add_argument("--only-if-continuous-idle", action="store_true", default=True)
    args = ap.parse_args()

    deadline = datetime.now(timezone.utc) + timedelta(hours=args.hours)
    waves = []
    idx = 0
    log(f"booster start hours={args.hours} limit={args.limit}")

    while datetime.now(timezone.utc) < deadline:
        if STOP.is_file():
            log("STOP present — exit")
            break
        busy = land_busy()
        # Only fire if no focus/drain active. Prefer continuous primary:
        # if continuous alive AND focus/drain busy → sleep.
        if busy.get("busy", 0) > 0:
            log(f"land busy {busy} — sleep {args.sleep}s")
            time.sleep(args.sleep)
            continue
        # If continuous is mid-tick with orch only, wait (orch may spawn focus)
        if busy.get("silo_orchestrator_tick.py", 0) > 0:
            log(f"orch active {busy} — sleep {args.sleep}s")
            time.sleep(args.sleep)
            continue
        # Continuous idle (or missing): run one gold wave
        src = GOLD[idx % len(GOLD)]
        idx += 1
        log(f"wave source={src}")
        res = run_wave(src, args.limit)
        waves.append({"at": utc(), "source": src, **res})
        log(f"wave done planned={res.get('planned')} copied={res.get('copied')} code={res.get('code')}")
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(
            "# Overnight land booster\n\n```json\n"
            + json.dumps({"at": utc(), "waves": waves[-20:], "busy_last": busy}, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )
        time.sleep(max(30, args.sleep // 2))

    log(f"booster done waves={len(waves)}")
    print(json.dumps({"waves": len(waves), "receipt": str(RECEIPT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
