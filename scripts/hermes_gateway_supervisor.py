#!/usr/bin/env python3
"""Hermes gateway process supervisor — permanent Discord stability layer.

Why this exists (2026-07-17):
  PowerShell keepalive can die or hang on Get-NetTCPConnection during long
  Discord turns. When both gateway and keepalive die, Discord stays mute until
  a human restarts. This supervisor is a detached pythonw loop that:

  1. Probes HTTP :8642/health every INTERVAL_SEC (no PS, no CIM)
  2. Clears stale gateway.pid/lock when claimed PID is dead
  3. Starts -m gateway.run via venv pythonw when down
  4. Logs every tick so silence = supervisor itself is dead
  5. Single-instance via lock file

Usage:
  pythonw D:\\HermesData\\scripts\\hermes_gateway_supervisor.py
  python  D:\\HermesData\\scripts\\hermes_gateway_supervisor.py --once
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
LOG = ROOT / "logs" / "gateway-supervisor.log"
STATE = ROOT / "state"
LOCK = STATE / "gateway-supervisor.lock"
HEARTBEAT = STATE / "gateway-supervisor-heartbeat.json"
PORT = 8642
INTERVAL_SEC = 15
BOOT_WAIT_SEC = 70
VENV_PYW = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
VENV_PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
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
        )
        out = (r.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out
    except Exception:
        return False


def health_ok(timeout: float = 3.0) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/health",
            method="GET",
            headers={"User-Agent": "hermes-gateway-supervisor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def port_listen(timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=timeout):
            return True
    except OSError:
        return False


def clear_stale_markers() -> list[str]:
    cleared: list[str] = []
    for name in ("gateway.pid", "gateway.lock", "gateway_state.json"):
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
            pid = 0
            if raw.startswith("{"):
                data = json.loads(raw)
                pid = int(data.get("pid") or 0)
            else:
                try:
                    pid = int(raw.split()[0])
                except Exception:
                    pid = 0
            if pid and pid_alive(pid):
                continue
            path.unlink(missing_ok=True)
            cleared.append(name)
        except Exception:
            try:
                path.unlink(missing_ok=True)
                cleared.append(name)
            except Exception:
                pass
    return cleared


def list_gateway_pids() -> list[int]:
    """Live python gateway processes only (not powershell that mentions gateway)."""
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python(w)?\\.exe' -and $_.CommandLine -and "
        "($_.CommandLine -match '-m\\s+gateway\\.run' -or "
        "$_.CommandLine -match 'hermes_cli\\.main.*gateway' -or "
        "$_.CommandLine -match 'hermes-agent[\\\\/]gateway[\\\\/]run\\.py') } | "
        "ForEach-Object { $_.ProcessId }"
    )
    pids: list[int] = []
    try:
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            if sys.platform == "win32"
            else 0
        )
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
    except Exception:
        pass
    return pids


def start_gateway() -> bool:
    clear_stale_markers()
    if health_ok():
        return True
    pyw = VENV_PYW if VENV_PYW.is_file() else VENV_PY
    if not pyw.is_file():
        log(f"ERR no pythonw at {pyw}")
        return False
    env = os.environ.copy()
    env["HERMES_HOME"] = str(ROOT)
    env["HERMES_CONFIG_PATH"] = str(ROOT / "config.yaml")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["HERMES_GATEWAY_DETACHED"] = "1"
    # Integrity timeout must not block gateway start (universal Discord stability).
    env["PHRONESIS_BOOT_INTEGRITY_MODE"] = "fast"
    env["PHRONESIS_BOOT_INTEGRITY_FAIL"] = "warn"
    creation = 0
    if sys.platform == "win32":
        creation = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | 0x08000000
        )
    try:
        subprocess.Popen(
            [str(pyw), "-m", "gateway.run"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creation,
            close_fds=True,
            env=env,
        )
        log(f"started {pyw} -m gateway.run")
    except Exception as exc:
        log(f"ERR start: {exc}")
        return False
    deadline = time.time() + BOOT_WAIT_SEC
    while time.time() < deadline:
        if health_ok():
            log("health OK after start")
            return True
        time.sleep(2)
    log("ERR start timed out waiting for /health")
    return False


def write_heartbeat(ok: bool, extra: dict | None = None) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "ts": _utc(),
            "ok": ok,
            "health": health_ok(timeout=2.0),
            "port": port_listen(),
            "gw_pids": list_gateway_pids(),
        }
        if extra:
            payload.update(extra)
        HEARTBEAT.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def acquire_lock() -> bool:
    STATE.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            if old > 0 and pid_alive(old):
                log(f"exit: another supervisor alive pid={old}")
                return False
        except Exception:
            pass
    LOCK.write_text(f"{os.getpid()} {_utc()}", encoding="utf-8")
    return True


def release_lock() -> None:
    try:
        if LOCK.is_file():
            raw = LOCK.read_text(encoding="utf-8")
            if raw.startswith(str(os.getpid())):
                LOCK.unlink(missing_ok=True)
    except Exception:
        pass


def tick() -> str:
    cleared = clear_stale_markers()
    if cleared:
        log(f"cleared_stale {cleared}")
    ok = health_ok()
    if ok:
        write_heartbeat(True)
        return "OK"
    # Boot race: process already starting — wait, do not dual-spawn.
    existing = list_gateway_pids()
    if existing:
        log(f"boot_wait pids={existing} (no dual start)")
        deadline = time.time() + BOOT_WAIT_SEC
        while time.time() < deadline:
            if health_ok():
                write_heartbeat(True, {"waited_boot": True})
                return "OK_after_boot_wait"
            time.sleep(2)
        log(f"boot_wait expired; killing hung pids={existing}")
        for pid in existing:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=15,
                )
            except Exception:
                pass
        time.sleep(2)
    log("DOWN health=False -> start_gateway")
    started = start_gateway()
    write_heartbeat(started, {"recovered": started})
    return "RECOVERED" if started else "FAIL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL_SEC)
    args = ap.parse_args()

    if args.once:
        log(f"once tick result={tick()}")
        return 0 if health_ok() else 1

    if not acquire_lock():
        return 0
    log(f"supervisor loop start pid={os.getpid()} interval={args.interval}s")
    try:
        while True:
            try:
                result = tick()
                log(result)
                # refresh lock
                try:
                    LOCK.write_text(f"{os.getpid()} {_utc()}", encoding="utf-8")
                except Exception:
                    pass
            except Exception as exc:
                log(f"LOOP_ERR {exc}")
            time.sleep(max(5, int(args.interval)))
    finally:
        release_lock()
        log(f"supervisor exit pid={os.getpid()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
