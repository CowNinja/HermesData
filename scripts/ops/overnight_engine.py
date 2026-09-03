#!/usr/bin/env python3
"""Jeff-asleep HEAVY engine. GPU/CPU work every cycle. 45s idle is dead.

Sequence: RAG embed → KG extract → VTT chaos → unit tests → janitor → prove.
If queue unlocked, fill and run-all (rclone). No SAT --heal. No Photos embed.

  python D:\\HermesData\\scripts\\ops\\overnight_engine.py --hours 8
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OPS = Path(r"D:\HermesData\scripts\ops")
STATE = Path(r"D:\HermesData\state")
LOCK = STATE / "nightly_queue.lock"
PY = sys.executable
PAD = Path(r"D:\Documents\browser-migration-2026-08-28")
LIFE = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Life-Archive"
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def run(script: str, args: list[str] | None = None, timeout: float | None = None) -> tuple[int, str]:
    cmd = [PY, "-u", str(OPS / script), *(args or [])]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(OPS),
        stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    out = ((r.stdout or "") + (r.stderr or ""))[-600:]
    print(out[-400:], flush=True)
    return r.returncode, out


def board(note: str) -> None:
    cfree = shutil.disk_usage("C:\\").free / (1024**3)
    prove = {}
    p = STATE / "life_rag_prove.json"
    if p.is_file():
        try:
            prove = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prove = {}
    chaos = {}
    c = STATE / "chaos_vtt.json"
    if c.is_file():
        try:
            chaos = json.loads(c.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            chaos = {}
    kg = STATE / "life_rag" / "kg.jsonl"
    kg_n = 0
    if kg.is_file():
        kg_n = sum(1 for _ in kg.open(encoding="utf-8", errors="replace"))
    rag = STATE / "life_rag" / "chunks.jsonl"
    rag_n = 0
    if rag.is_file():
        rag_n = sum(1 for _ in rag.open(encoding="utf-8", errors="replace"))
    text = "\n".join(
        [
            "# 00-STATUS — overnight swarm",
            f"stamped={utc()}",
            f"C_FREE_GB={cfree:.2f}",
            f"note={note}",
            f"rag_chunks={rag_n} rag_prove={prove.get('ok')}/{prove.get('n')}",
            f"kg_triples={kg_n} chaos_p99={chaos.get('p99_ms')} vtt_n={chaos.get('n')}",
            "K: onedrive-* never deleted. Photos bytes not in RAG. Patient-BLOOM untouched.",
            "",
        ]
    )
    for dest in (PAD / "00-STATUS.md", LIFE / "00-STATUS.md"):
        try:
            dest.write_text(text, encoding="utf-8")
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8)
    args = ap.parse_args()
    deadline = time.time() + args.hours * 3600
    n = 0
    while time.time() < deadline:
        n += 1
        print(f"HEAVY_CYCLE {n}", flush=True)
        run("hermes_master_daemon.py", ["--ensure"])
        run("sovereign_disk_sentinel.py")  # C: vacuum if free < 26 GB; never SAT heal
        run("mma_harvester.py", ["--check-free"])  # free roster + local leaderboard; no C: weights
        run("life_rag.py", ["embed"])  # refuses jsonl corpse; ANN is query path
        run("live_sweep.py")
        run("contacts_refine.py")
        run("contacts_sanity_check.py")
        run("contacts_label_purge.py")
        run("fuzzy_deconfliction.py")
        run("contacts_semantic_refiner.py")
        run("contacts_org_sweep.py")
        run("contacts_nomen_sweep.py")
        run("contacts_osint.py")
        run("contacts_anchor.py")
        run("contacts_audit.py")
        run("life_kg.py")
        run("midnight_harvest.py", ["--local"])
        run("kg_reasoner.py")
        run("contacts_graph_enrich.py")
        run("places_calendar_audit.py")
        run("universal_ingestor.py")
        run("global_sanity.py")
        run("contacts_comms_sync.py")
        run("bw_username_close.py")
        run("chaos_vtt.py", ["--n", "4000"])
        run("test_vtt_forgive.py")
        run("janitor_waste.py")
        run("life_rag.py", ["prove"])
        if not LOCK.exists():
            run("queue_fill_next.py")
            run("nightly_queue.py", ["run-all"])
        if n % 3 == 0:
            run("router_mm_eval_once.py")
        board(f"heavy_cycle={n}")
        _maybe_morning_pulse()
        time.sleep(3)
    board("heavy_done")
    run("morning_pulse.py")
    print("OVERNIGHT_HEAVY_DONE", flush=True)
    return 0


def _et_hour() -> int:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=4)).hour


def _maybe_morning_pulse() -> None:
    stamp = STATE / "morning_pulse_day.txt"
    day = utc()[:10]
    if _et_hour() not in (6, 7):
        return
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == day:
        return
    run("morning_pulse.py")
    try:
        stamp.write_text(day, encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
