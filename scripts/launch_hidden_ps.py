#!/usr/bin/env python3
"""Run a PowerShell .ps1 with CREATE_NO_WINDOW — no focus steal on Win11.

Task Scheduler should invoke this via pythonw.exe, not powershell.exe:

  pythonw.exe D:\\HermesData\\scripts\\launch_hidden_ps.py D:\\path\\script.ps1 [-Quiet]

Even -WindowStyle Hidden still allocates conhost when schtasks starts powershell.exe
directly (see SuperUser / Hermes-agent #54282). pythonw + CREATE_NO_WINDOW does not.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: launch_hidden_ps.py <script.ps1> [args...]", file=sys.stderr)
        return 2
    ps1 = sys.argv[1]
    extra = sys.argv[2:]
    if not Path(ps1).is_file():
        print(f"missing script: {ps1}", file=sys.stderr)
        return 2

    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        ps1,
        *extra,
    ]
    si = subprocess.STARTUPINFO()
    si.dwFlags |= STARTF_USESHOWWINDOW
    si.wShowWindow = SW_HIDE
    flags = (
        CREATE_NO_WINDOW
        | DETACHED_PROCESS
        | CREATE_NEW_PROCESS_GROUP
        | CREATE_BREAKAWAY_FROM_JOB
    )
    env = os.environ.copy()
    env["HERMES_HIDDEN_CHILD"] = "1"
    try:
        r = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            startupinfo=si,
            env=env,
            cwd=str(Path(ps1).parent),
        )
        return int(r.returncode)
    except OSError:
        flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        r = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            startupinfo=si,
            env=env,
            cwd=str(Path(ps1).parent),
        )
        return int(r.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
