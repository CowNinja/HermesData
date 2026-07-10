#!/usr/bin/env python3
"""Force Hermes gateway restart for Grok 4.5 switch (travel mode).

Previous attempt blocked on discord_turn_in_flight. This uses -ForceGateway
then falls back to taskkill + Hermes_Gateway scheduled task.
"""
from __future__ import annotations

import json
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
SLEEP_SEC = 20


def log(event: dict) -> None:
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    print(json.dumps(event), flush=True)


def run(cmd: list[str], timeout: int = 240) -> dict:
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
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-800:],
        }
    except Exception as e:
        return {"cmd": cmd, "error": str(e)}


def read_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
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
    log({"event": "force_start", "sleep_sec": SLEEP_SEC, "reason": "grok-4.5 force restart after discord_turn_in_flight block"})
    time.sleep(SLEEP_SEC)

    old_pid = read_pid()
    log({"event": "pre_restart", "pid": old_pid, "port_8642": port_open()})

    # 1) Official force path
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
                "-ForceGateway",
            ],
            timeout=300,
        )
        log({"event": "phronesis_force_restart", **res})
        time.sleep(15)
        new_pid = read_pid()
        if port_open() and new_pid and new_pid != old_pid:
            log({"event": "success", "method": "phronesis_force", "port_8642": True, "old_pid": old_pid, "new_pid": new_pid})
            return 0
        if port_open() and res.get("code") == 0:
            log({"event": "success_port_up", "method": "phronesis_force", "port_8642": True, "old_pid": old_pid, "new_pid": new_pid})
            return 0

    # 2) Hard fallback: kill + scheduled task
    if old_pid:
        kill = run(["taskkill", "/F", "/PID", str(old_pid)], timeout=30)
        log({"event": "taskkill", **kill})
        time.sleep(4)
        # also kill any leftover gateway pythonw on hermes_cli.main gateway
        run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'hermes_cli.main gateway' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
            ],
            timeout=30,
        )
        time.sleep(3)

    start = run(["schtasks", "/Run", "/TN", "Hermes_Gateway"], timeout=60)
    log({"event": "schtasks_run", **start})

    # wait for port
    for i in range(20):
        time.sleep(3)
        if port_open():
            new_pid = read_pid()
            log(
                {
                    "event": "success",
                    "method": "schtasks_fallback",
                    "port_8642": True,
                    "old_pid": old_pid,
                    "new_pid": new_pid,
                    "wait_sec": (i + 1) * 3,
                }
            )
            return 0

    log({"event": "failed", "port_8642": False, "old_pid": old_pid, "new_pid": read_pid()})
    return 1


if __name__ == "__main__":
    sys.exit(main())
