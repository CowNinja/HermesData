#!/usr/bin/env python3
"""Launch unattended autonomous sprint in background (Windows-friendly).

Uses wscript so the sprint process is not tied to the parent Job Object
(Grok shells / PowerShell jobs kill children on exit).
Sprint itself calls FreeConsole() so no focus steal.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
STATE = Path(r"D:/HermesData/state")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from windows_subprocess import run_hidden  # noqa: E402

PY = r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
SPRINT = str(SCRIPTS / "silo_autonomous_sprint.py")
VBS = SCRIPTS / "start_silo_sprint_only_hidden.vbs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--sleep", type=int, default=25)
    args = ap.parse_args()
    stop = STATE / "silo_autonomous.STOP"
    if stop.exists():
        stop.unlink()
    log = STATE / "silo_autonomous_sprint_bg.log"

    # Write a dedicated VBS for this launch (hours/sleep vary)
    VBS.write_text(
        "Option Explicit\r\n"
        "Dim sh\r\n"
        "Set sh = CreateObject(\"WScript.Shell\")\r\n"
        f'sh.Run """{PY}"" ""{SPRINT}"" --hours {args.hours} --sleep {args.sleep} --smoke", 0, False\r\n',
        encoding="ascii",
    )
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n--- launch {args.hours}h via wscript py={PY} ---\n")

    run_hidden(["wscript.exe", "//B", str(VBS)], timeout=15)
    time.sleep(1.2)

    pid = None
    try:
        r = run_hidden(
            [
                "powershell",
                "-NoProfile",
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
            timeout=20,
        )
        pid = int((r.stdout or "0").strip().splitlines()[-1])
    except Exception:
        pid = None
    if pid:
        (STATE / "silo_autonomous_sprint.pid").write_text(str(pid), encoding="utf-8")
    print({"pid": pid, "hours": args.hours, "log": str(log), "py": PY, "via": "wscript"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
