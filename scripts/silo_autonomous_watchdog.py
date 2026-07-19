#!/usr/bin/env python3
"""Autonomous flake watchdog — if BG sprint stalls, restart lightly.

Run via schtasks / cron every 15–30m. Zero Grok. No land multi-writer.

Stall rule: bg log mtime older than --stall-minutes while pid alive and hours not expired.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:/HermesData/state")
SCRIPTS = Path(r"D:/HermesData/scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from windows_subprocess import prefer_pythonw, run_hidden  # noqa: E402

# Prefer pythonw so relaunch chain never attaches a console.
_PY_CANDIDATES = [
    Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"),
    Path(prefer_pythonw(sys.executable)),
    Path(sys.executable),
]
PY = str(next((p for p in _PY_CANDIDATES if p.is_file()), Path(sys.executable)))
PID_F = STATE / "silo_autonomous_sprint.pid"
LOG = STATE / "silo_autonomous_sprint_bg.log"
STOP = STATE / "silo_autonomous.STOP"
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-autonomous-watchdog-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def alive(pid: int) -> bool:
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if h:
            k.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def kill(pid: int) -> None:
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(1, False, pid)
        if h:
            k.TerminateProcess(h, 1)
            k.CloseHandle(h)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stall-minutes", type=float, default=12)
    # Overnight default 9h (was 4) so schtasks relaunch covers full sleep window
    ap.add_argument("--hours", type=float, default=9)
    ap.add_argument("--sleep", type=int, default=30)
    args = ap.parse_args()
    actions = []
    if STOP.is_file():
        msg = {"at": utc(), "action": "stop_present", "restart": False}
        RECEIPT.write_text(json.dumps(msg, indent=2), encoding="utf-8")
        print(json.dumps(msg))
        return 0
    pid = None
    if PID_F.is_file():
        try:
            pid = int(PID_F.read_text().strip())
        except Exception:
            pid = None
    stalled = False
    age_min = None
    if LOG.is_file():
        age_min = (time.time() - LOG.stat().st_mtime) / 60.0
        if age_min >= args.stall_minutes:
            stalled = True
    need_restart = False
    if pid and alive(pid) and stalled:
        kill(pid)
        actions.append(f"killed_stalled_pid_{pid}_age_{age_min:.1f}m")
        need_restart = True
    elif pid and not alive(pid):
        actions.append(f"dead_pid_{pid}")
        need_restart = True
    elif not pid:
        actions.append("no_pid")
        need_restart = True
    if need_restart and not STOP.is_file():
        r = run_hidden(
            [
                PY,
                str(SCRIPTS / "silo_autonomous_launch.py"),
                "--hours",
                str(args.hours),
                "--sleep",
                str(args.sleep),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        actions.append(f"relaunch_exit_{r.returncode}")
        actions.append((r.stdout or "")[:200])
    msg = {
        "at": utc(),
        "pid": pid,
        "log_age_min": age_min,
        "stalled": stalled,
        "actions": actions,
        "need_restart": need_restart,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"# Autonomous watchdog — {msg['at']}\n\n```json\n{json.dumps(msg, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(msg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
