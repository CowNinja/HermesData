#!/usr/bin/env python3
"""Long-running popup storm daemon (travel mode, no Admin).

Loops every 15s: END admin flash schtasks + stop Cua + keep focus STOPs.
Start: pythonw popup_storm_daemon.py
Stop: write D:\\HermesData\\state\\popup_storm_daemon.STOP
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state")
sys.path.insert(0, str(SCRIPTS))

from popup_storm_suppress import suppress  # noqa: E402

PID_FILE = STATE / "popup_storm_daemon.pid"
STOP_FILE = STATE / "popup_storm_daemon.STOP"
# Travel mode: tighter than minute schtask so flash windows die before user notices.
INTERVAL_SEC = 5


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    if STOP_FILE.is_file():
        try:
            STOP_FILE.unlink()
        except Exception:
            pass
    PID_FILE.write_text(str(__import__("os").getpid()), encoding="utf-8")
    # FreeConsole if attached
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass
    while True:
        if STOP_FILE.is_file():
            break
        try:
            suppress()
        except Exception:
            pass
        for _ in range(INTERVAL_SEC):
            if STOP_FILE.is_file():
                break
            time.sleep(1)
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
