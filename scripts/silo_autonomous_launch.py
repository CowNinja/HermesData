#!/usr/bin/env python3
"""Launch unattended autonomous sprint in background (Windows-friendly).

Creates no window spam; writes PID + log. Local only.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
STATE = Path(r"D:/HermesData/state")
PY = sys.executable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--sleep", type=int, default=25)
    args = ap.parse_args()
    stop = STATE / "silo_autonomous.STOP"
    if stop.exists():
        stop.unlink()
    log = STATE / "silo_autonomous_sprint_bg.log"
    cmd = [
        PY,
        str(SCRIPTS / "silo_autonomous_sprint.py"),
        "--hours",
        str(args.hours),
        "--sleep",
        str(args.sleep),
        "--smoke",
    ]
    # detached-ish
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n--- launch {args.hours}h ---\n")
        proc = subprocess.Popen(
            cmd,
            cwd=str(SCRIPTS),
            stdout=f,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0,
        )
    (STATE / "silo_autonomous_sprint.pid").write_text(str(proc.pid), encoding="utf-8")
    print({"pid": proc.pid, "hours": args.hours, "log": str(log), "stop": str(stop)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
