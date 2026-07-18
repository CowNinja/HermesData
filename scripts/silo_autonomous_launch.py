#!/usr/bin/env python3
"""Launch unattended autonomous sprint in background (Windows-friendly).

Uses wscript / launch_console_hidden so the sprint is not tied to the parent
Job Object (Grok shells / PowerShell jobs kill children on exit).
Sprint itself calls FreeConsole() so no focus steal.

Overnight 2026-07-18: robust PID capture (CIM + tasklist fallback).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
STATE = Path(r"D:/HermesData/state")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from windows_subprocess import run_hidden  # noqa: E402

PY = r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
PYW = r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
SPRINT = str(SCRIPTS / "silo_autonomous_sprint.py")
LAUNCHER = str(SCRIPTS / "launch_console_hidden.py")
VBS = SCRIPTS / "start_silo_sprint_only_hidden.vbs"
PID_F = STATE / "silo_autonomous_sprint.pid"
LOG = STATE / "silo_autonomous_sprint_bg.log"


def _find_sprint_pid() -> int | None:
    """Return first live python* PID whose command line includes silo_autonomous_sprint.py."""
    # Prefer CIM via PowerShell (hidden)
    try:
        r = run_hidden(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "(Get-CimInstance Win32_Process | Where-Object { "
                "$_.CommandLine -like '*silo_autonomous_sprint.py*' "
                "-and $_.Name -like 'python*' } | "
                "Select-Object -First 1 -ExpandProperty ProcessId)",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        txt = (r.stdout or "").strip()
        if txt:
            for line in reversed(txt.splitlines()):
                line = line.strip()
                if line.isdigit():
                    return int(line)
    except Exception:
        pass
    # Fallback: wmic
    try:
        r = run_hidden(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe' or name='pythonw.exe'",
                "get",
                "ProcessId,CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        for line in (r.stdout or "").splitlines():
            if "silo_autonomous_sprint.py" not in line:
                continue
            m = re.search(r"\b(\d+)\s*$", line.strip())
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--sleep", type=int, default=25)
    args = ap.parse_args()
    stop = STATE / "silo_autonomous.STOP"
    if stop.exists():
        stop.unlink()

    # Dedicated VBS: pythonw launcher → breakaway console-hidden sprint
    hours = float(args.hours)
    sleep = int(args.sleep)
    vbs_body = (
        "Option Explicit\r\n"
        "Dim sh\r\n"
        "Set sh = CreateObject(\"WScript.Shell\")\r\n"
        f'sh.Run """{PYW}"" ""{LAUNCHER}"" -- ""{PY}"" ""{SPRINT}"" --hours {hours} --sleep {sleep} --smoke", 0, False\r\n'
    )
    VBS.write_text(vbs_body, encoding="ascii")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n--- launch {hours}h via wscript+launch_console_hidden py={PY} ---\n")

    run_hidden(["wscript.exe", "//B", str(VBS)], timeout=15)
    # Give process time to appear
    pid = None
    for _ in range(8):
        time.sleep(0.8)
        pid = _find_sprint_pid()
        if pid:
            break
    if pid:
        PID_F.write_text(str(pid), encoding="utf-8")
    else:
        # leave stale pid cleared so watchdog retries cleanly
        try:
            if PID_F.is_file():
                PID_F.unlink()
        except Exception:
            pass
    print({"pid": pid, "hours": hours, "log": str(LOG), "py": PY, "via": "wscript+launch_console_hidden"})
    return 0 if pid else 1


if __name__ == "__main__":
    raise SystemExit(main())
