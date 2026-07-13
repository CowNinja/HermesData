#!/usr/bin/env python3
"""Overnight silo watchdog — restart continuous if state stale; never touch gateway.

Safe for Task Scheduler every 15–30 min. $0 LLM.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state\silo_continuous_state.json")
STOP = Path(r"D:\HermesData\state\silo_continuous.STOP")
PIDF = Path(r"D:\HermesData\state\silo_continuous.pid")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-overnight-watchdog-latest.md")
PY = r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
SCRIPT = r"D:\HermesData\scripts\silo_continuous_loop.py"
STALE_S = 900  # 15 min


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    prev = LOG.read_text(encoding="utf-8") if LOG.is_file() else "# overnight watchdog\n\n"
    LOG.write_text(prev + line + "\n", encoding="utf-8")


def continuous_running() -> bool:
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*silo_continuous_loop.py*' -and $_.Name -like 'python*' } | Measure-Object | Select-Object -ExpandProperty Count",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return int((r.stdout or "0").strip() or "0") > 0
    except Exception:
        return False


def start_continuous() -> int:
    # Do not start a second owner
    if continuous_running():
        return -1
    # Respect STOP — never clear it here (Jeff / operator owns STOP)
    if STOP.is_file():
        return -2
    out = open(r"D:\HermesData\state\silo_continuous_stdout.log", "a", encoding="utf-8")
    err = open(r"D:\HermesData\state\silo_continuous_stderr.log", "a", encoding="utf-8")
    flags = 0x00000008 | 0x00000200
    p = subprocess.Popen(
        [PY, SCRIPT, "--max-cycles", "0", "--force-mode", "aggressive"],
        cwd=r"D:\HermesData",
        stdout=out,
        stderr=err,
        creationflags=flags,
    )
    PIDF.write_text(str(p.pid), encoding="utf-8")
    return p.pid


def main() -> int:
    if STOP.is_file():
        log("STOP file present — no restart")
        return 0
    age = None
    if STATE.is_file():
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            at = datetime.fromisoformat(d["at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - at).total_seconds()
        except Exception as e:
            log(f"state parse err {e}")
    running = continuous_running()
    if running and age is not None and age < STALE_S:
        log(f"ok running age={int(age)}s")
        return 0
    if running and age is not None and age >= STALE_S:
        log(f"stale age={int(age)}s — kill then single restart")
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*silo_continuous_loop.py*' -and $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
            ],
            timeout=60,
        )
        import time as _t

        _t.sleep(2)
    elif not running:
        log("not running — start")
    else:
        log("running age unknown — leave alone")
        return 0
    pid = start_continuous()
    log(f"started pid={pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
