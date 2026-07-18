#!/usr/bin/env python3
"""Meta-watchdog v2: keep hermes_gateway_SERVICE alive (Red-style outer loop).

Does NOT start gateway.run directly (avoids dual-start races).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "state"
LOCK = STATE / "gateway-meta-watchdog.lock"
SVC_LOCK = STATE / "gateway-service.lock"
LOG = ROOT / "logs" / "gateway-meta-watchdog.log"
INTERVAL = 15
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
BREAKAWAY = 0x01000000
VENV_PYW = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out = (r.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out
    except Exception:
        return False


def service_alive() -> bool:
    if SVC_LOCK.is_file():
        try:
            pid = int(SVC_LOCK.read_text(encoding="utf-8").strip().split()[0])
            if pid_alive(pid):
                return True
        except Exception:
            pass
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "(Get-CimInstance Win32_Process | Where-Object { "
                "$_.CommandLine -like '*hermes_gateway_service.py*' }).Count",
            ],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return int((r.stdout or "0").strip() or "0") > 0
    except Exception:
        return False


def health() -> bool:
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:8642/health",
            headers={"User-Agent": "meta-watchdog/2.0"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def start_service() -> None:
    """Start gateway-service outside Job Objects (WMI via start_detached)."""
    det = SCRIPTS / "start_detached.py"
    pyw = str(VENV_PYW if VENV_PYW.is_file() else sys.executable)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(ROOT)
    env["PHRONESIS_BOOT_INTEGRITY"] = "0"
    if det.is_file():
        try:
            subprocess.run(
                [pyw, str(det), str(SCRIPTS / "hermes_gateway_service.py")],
                cwd=str(ROOT),
                timeout=45,
                capture_output=True,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                env=env,
            )
            log("started hermes_gateway_service (via start_detached/WMI)")
            return
        except Exception as exc:
            log(f"start_detached err: {exc}")
    flags = CREATE_NO_WINDOW | NEW_GROUP | BREAKAWAY
    try:
        subprocess.Popen(
            [pyw, str(SCRIPTS / "hermes_gateway_service.py")],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags if sys.platform == "win32" else 0,
            close_fds=True,
            env=env,
        )
    except OSError:
        flags = CREATE_NO_WINDOW | NEW_GROUP | DETACHED
        subprocess.Popen(
            [pyw, str(SCRIPTS / "hermes_gateway_service.py")],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags if sys.platform == "win32" else 0,
            close_fds=True,
            env=env,
        )
    log("started hermes_gateway_service (popen fallback)")


def acquire() -> bool:
    STATE.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            if old > 0 and pid_alive(old) and old != os.getpid():
                log(f"exit: meta already pid={old}")
                return False
        except Exception:
            pass
    LOCK.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")
    return True


def main() -> int:
    if not acquire():
        return 0
    log(f"meta-watchdog v2 start pid={os.getpid()} (owns gateway-service only)")
    try:
        while True:
            try:
                if not service_alive():
                    log("gateway-service DEAD -> restart")
                    start_service()
                    time.sleep(10)
                else:
                    log(
                        f"OK service_alive=True gateway_health={health()}"
                    )
                LOCK.write_text(
                    f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8"
                )
            except Exception as exc:
                log(f"ERR {exc}")
            time.sleep(INTERVAL)
    finally:
        try:
            if LOCK.is_file() and LOCK.read_text(encoding="utf-8").startswith(
                str(os.getpid())
            ):
                LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
