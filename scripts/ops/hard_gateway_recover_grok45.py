#!/usr/bin/env python3
"""OUT-OF-BAND Hermes gateway hard recovery for Grok 4.5 switch.

Must run OUTSIDE the gateway process tree (via Windows scheduled task).
Kills all hermes_cli.main gateway processes, starts Hermes_Gateway task,
verifies port 8642 + fresh PID.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(r"D:\HermesData\logs\hard_gateway_recover_grok45.jsonl")
LOG.parent.mkdir(parents=True, exist_ok=True)
PID_FILES = [
    Path(r"C:\Users\CowNi\.hermes\gateway.pid"),
    Path(r"D:\HermesData\gateway.pid"),
]


def log(event: dict) -> None:
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    print(json.dumps(event), flush=True)


def port_open(port: int = 8642) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def gateway_pids() -> list[int]:
    r = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'hermes_cli.main gateway' } | ForEach-Object { $_.ProcessId }",
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    out: list[int] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            out.append(int(line))
    return out


def main() -> int:
    log({"event": "oob_start", "reason": "grok-4.5 hard recover (in-gateway restart blocked)"})
    before = gateway_pids()
    log({"event": "pre", "pids": before, "port_8642": port_open()})

    # Kill every gateway process
    for pid in before:
        r = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        log(
            {
                "event": "taskkill",
                "pid": pid,
                "code": r.returncode,
                "stdout": (r.stdout or "")[-200:],
                "stderr": (r.stderr or "")[-200:],
            }
        )
    time.sleep(3)
    for pid in gateway_pids():
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, text=True, timeout=20)

    time.sleep(2)
    log({"event": "after_kill", "pids": gateway_pids(), "port_8642": port_open()})

    # Start scheduled task
    r = subprocess.run(
        ["schtasks", "/Run", "/TN", "Hermes_Gateway"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    log(
        {
            "event": "schtasks_run",
            "code": r.returncode,
            "stdout": (r.stdout or "")[-400:],
            "stderr": (r.stderr or "")[-400:],
        }
    )

    # Wait for healthy gateway
    ok = False
    pids: list[int] = []
    for i in range(30):
        time.sleep(2)
        pids = gateway_pids()
        if port_open() and pids:
            ok = True
            break

    # Direct start fallback
    if not ok:
        log({"event": "direct_start_fallback"})
        env = os.environ.copy()
        env["HERMES_HOME"] = r"C:\Users\CowNi\.hermes"
        env["PYTHONIOENCODING"] = "utf-8"
        env["HERMES_GATEWAY_DETACHED"] = "1"
        CREATE_NO_WINDOW = 0x08000000
        DETACHED = 0x00000008
        cmd = [
            r"D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe",
            "-m",
            "hermes_cli.main",
            "gateway",
            "run",
        ]
        try:
            subprocess.Popen(
                cmd,
                cwd=r"D:\HermesData",
                env=env,
                creationflags=CREATE_NO_WINDOW | DETACHED,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as e:
            log({"event": "direct_start_error", "error": str(e)})
        for i in range(20):
            time.sleep(2)
            pids = gateway_pids()
            if port_open() and pids:
                ok = True
                break

    # Verify config default still grok-4.5
    model = None
    try:
        import yaml

        with open(r"C:\Users\CowNi\.hermes\config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        model = (cfg.get("model") or {}).get("default")
    except Exception as e:
        model = f"err:{e}"

    log(
        {
            "event": "oob_done",
            "ok": ok,
            "port_8642": port_open(),
            "pids": pids,
            "model_default": model,
            "pid_files": {str(p): (p.read_text(encoding="utf-8")[:120] if p.exists() else None) for p in PID_FILES},
        }
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
