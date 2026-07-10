#!/usr/bin/env python3
"""Delayed safe Hermes gateway restart for travel-mode Grok 4.5 switch.

Sleeps so the current Discord reply can deliver, then restarts gateway
via Phronesis.ps1 when possible, else PID kill + Hermes_Gateway task.
Logs everything under D:/HermesData/logs/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
LOG_DIR = HERMES / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "delayed_gateway_restart_grok45.jsonl"
PID_FILE = Path(r"C:\Users\CowNi\.hermes\gateway.pid")
PHRONESIS = HERMES / "scripts" / "Phronesis.ps1"
SLEEP_SEC = 25


def log(event: dict) -> None:
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    print(json.dumps(event), flush=True)


def run(cmd: list[str], timeout: int = 180) -> dict:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(HERMES),
        )
        return {
            "cmd": cmd,
            "code": r.returncode,
            "stdout": (r.stdout or "")[-800:],
            "stderr": (r.stderr or "")[-800:],
        }
    except Exception as e:
        return {"cmd": cmd, "error": str(e)}


def read_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        # may be plain int or JSON
        if raw.startswith("{"):
            return int(json.loads(raw).get("pid") or 0) or None
        return int(raw) or None
    except Exception:
        return None


def port_open(port: int = 8642) -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def main() -> int:
    log({"event": "start", "sleep_sec": SLEEP_SEC, "reason": "grok-4.5 config switch"})
    time.sleep(SLEEP_SEC)

    old_pid = read_pid()
    log({"event": "pre_restart", "pid": old_pid, "port_8642": port_open()})

    # Prefer official Phronesis gateway restart
    if PHRONESIS.is_file():
        res = run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PHRONESIS),
                "gateway",
                "restart",
            ],
            timeout=240,
        )
        log({"event": "phronesis_gateway_restart", **res})
        time.sleep(12)
        if port_open():
            log({"event": "success", "method": "phronesis", "port_8642": True, "new_pid": read_pid()})
            return 0

    # Fallback: kill old PID, start scheduled task
    if old_pid:
        kill = run(["taskkill", "/F", "/PID", str(old_pid)], timeout=30)
        log({"event": "taskkill", **kill})
        time.sleep(5)

    # Start via scheduled task
    start = run(["schtasks", "/Run", "/TN", "Hermes_Gateway"], timeout=60)
    log({"event": "schtasks_run", **start})
    time.sleep(15)

    ok = port_open()
    log(
        {
            "event": "done",
            "ok": ok,
            "port_8642": ok,
            "new_pid": read_pid(),
            "method": "schtasks_fallback",
        }
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
