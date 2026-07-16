#!/usr/bin/env python3
"""One-board autonomous kitchen status — zero Grok, local only."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:/HermesData/state")
OUT = Path(r"D:/PhronesisVault/Operations/logs/silo-autonomous-status-latest.md")


def line_count(p: Path) -> int:
    if not p.is_file():
        return 0
    n = 0
    with p.open(encoding="utf-8", errors="replace") as f:
        for _ in f:
            n += 1
    return n


def ocr_open() -> tuple[int, int]:
    try:
        c = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=20)
        d = dict(c.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
        c.close()
        open_n = int(d.get("needs_ocr") or 0) + int(d.get("queued") or 0) + int(d.get("error") or 0)
        return open_n, int(d.get("ok_text") or 0)
    except Exception:
        return -1, -1


def alive(pid: int) -> bool:
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if h:
            k.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def main() -> int:
    open_n, ok = ocr_open()
    pid_f = STATE / "silo_autonomous_sprint.pid"
    log = STATE / "silo_autonomous_sprint_bg.log"
    stop = STATE / "silo_autonomous.STOP"
    pid = int(pid_f.read_text().strip()) if pid_f.is_file() else None
    bg = bool(pid and alive(pid))
    age = (time.time() - log.stat().st_mtime) / 60.0 if log.is_file() else None
    board = {
        "at": datetime.now(timezone.utc).isoformat(),
        "era": "post_ocr" if open_n == 0 else "ocr_drain",
        "ocr_open": open_n,
        "ok_text": ok,
        "k_light": line_count(STATE / "k_light_index.jsonl"),
        "med_navy_index": line_count(STATE / "medical_navy_text_index.jsonl"),
        "bg_pid": pid,
        "bg_alive": bg,
        "log_age_min": round(age, 2) if age is not None else None,
        "stop_present": stop.is_file(),
        "retrieval_cache": (STATE / "twin_retrieval_cache.json").is_file(),
        "next_sources_plan": (STATE / "next_sources_plan.json").is_file(),
    }
    # optional pulse
    pulse = STATE / "silo_scoreboard_pulse.json"
    if pulse.is_file():
        try:
            board["pulse"] = json.loads(pulse.read_text(encoding="utf-8"))
        except Exception:
            pass
    lines = [
        f"# Autonomous status — {board['at']}",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Era | **{board['era']}** |",
        f"| OCR open | **{board['ocr_open']}** |",
        f"| ok_text | {board['ok_text']} |",
        f"| K-light | {board['k_light']} |",
        f"| Med/Navy index | {board['med_navy_index']} |",
        f"| BG | pid={board['bg_pid']} alive=**{board['bg_alive']}** age_min={board['log_age_min']} |",
        f"| STOP | {board['stop_present']} |",
        f"| Cache/plan | ret={board['retrieval_cache']} next={board['next_sources_plan']} |",
        "",
        "Runbook: [[Operations/Autonomous-Silo-Runbook-CANONICAL-2026-07-14]]",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(board, indent=2, default=str)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
