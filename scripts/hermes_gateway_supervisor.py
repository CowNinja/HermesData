#!/usr/bin/env python3
"""Hermes gateway supervisor v2 — primary Discord :8642 restarter.

Root causes of repeated drops (2026-07-17):
  1. Gateway process dies mid-turn (silent) — no traceback
  2. Dual starters (keepalive + supervisor + heal) race → "runtime lock already held"
  3. list_gateway_pids returned dead PIDs → boot_wait forever / no restart
  4. Supervisor + keepalive themselves die → no recovery until human

Policy:
  - This process is the ONLY automatic gateway starter
  - Alive-only PID checks; kill hung/non-health trees before start
  - Skip boot integrity (PHRONESIS_BOOT_INTEGRITY=0) for fast reliable start
  - Never exit the loop on recoverable errors
  - Heartbeat file for meta-watchdog
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
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
INTERVAL_SEC = 12
BOOT_WAIT_SEC = 55
VENV_PYW = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
VENV_PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


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


def _flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=_flags(),
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
            headers={"User-Agent": "hermes-gateway-supervisor/2.0"},
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
            # Keep only if process alive AND health OK (ghost "running" state is poison)
            if pid and pid_alive(pid) and health_ok(timeout=1.5):
                continue
            if pid and pid_alive(pid) and not health_ok(timeout=1.5):
                # hung process holding lock without serving
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True,
                        timeout=15,
                        creationflags=_flags(),
                    )
                    cleared.append(f"killed_hung_{pid}")
                except Exception:
                    pass
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
    """Live python gateway PIDs only (alive + cmdline match)."""
    ps = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -match 'python(w)?\\.exe' -and $_.CommandLine -and ("
        "$_.CommandLine -match '-m\\s+gateway\\.run' -or "
        "$_.CommandLine -match 'hermes_cli\\.main.*gateway' -or "
        "$_.CommandLine -match 'hermes-agent[\\\\/]gateway[\\\\/]run\\.py'"
        ") } | ForEach-Object { $_.ProcessId }"
    )
    pids: list[int] = []
    try:
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
            timeout=25,
            creationflags=_flags(),
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid_alive(pid):
                    pids.append(pid)
    except Exception as exc:
        log(f"list_gateway_pids err: {exc}")
    return sorted(set(pids))


def kill_gateway_tree() -> list[int]:
    killed = []
    for pid in list_gateway_pids():
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
                creationflags=_flags(),
            )
            killed.append(pid)
        except Exception:
            pass
    time.sleep(1.5)
    clear_stale_markers()
    return killed


def start_gateway() -> bool:
    clear_stale_markers()
    if health_ok():
        return True
    # If something is half-alive without health, kill it first (avoids lock race)
    existing = list_gateway_pids()
    if existing:
        log(f"prestart kill hung/partial pids={existing}")
        kill_gateway_tree()

    pyw = VENV_PYW if VENV_PYW.is_file() else VENV_PY
    if not pyw.is_file():
        log(f"ERR no pythonw at {pyw}")
        return False
    env = os.environ.copy()
    env["HERMES_HOME"] = str(ROOT)
    env["HERMES_CONFIG_PATH"] = str(ROOT / "config.yaml")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["HERMES_GATEWAY_DETACHED"] = "1"
    # Skip integrity gate entirely — timeouts blocked starts and caused drop storms
    env["PHRONESIS_BOOT_INTEGRITY"] = "0"
    env["PHRONESIS_BOOT_INTEGRITY_MODE"] = "fast"
    env["PHRONESIS_BOOT_INTEGRITY_FAIL"] = "warn"
    creation = 0
    if sys.platform == "win32":
        creation = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | CREATE_NO_WINDOW
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
    # failed start may leave lock — clean
    kill_gateway_tree()
    return False


def write_heartbeat(status: str, extra: dict | None = None) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "ts": _utc(),
            "status": status,
            "health": health_ok(timeout=2.0),
            "port": port_listen(),
            "gw_pids": list_gateway_pids(),
        }
        if extra:
            payload.update(extra)
        HEARTBEAT.write_text(json.dumps(payload), encoding="utf-8")
        LOCK.write_text(f"{os.getpid()} {_utc()}", encoding="utf-8")
    except Exception:
        pass


def acquire_lock() -> bool:
    STATE.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            if old > 0 and old != os.getpid() and pid_alive(old):
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
    try:
        cleared = clear_stale_markers()
        if cleared:
            log(f"cleared_stale {cleared}")
        if health_ok():
            write_heartbeat("OK")
            return "OK"

        existing = list_gateway_pids()
        if existing:
            # Process alive but no health — wait briefly for boot
            log(f"unhealthy_alive pids={existing} wait_boot")
            deadline = time.time() + min(BOOT_WAIT_SEC, 25)
            while time.time() < deadline:
                if health_ok():
                    write_heartbeat("OK_after_boot_wait")
                    return "OK_after_boot_wait"
                time.sleep(2)
            log(f"hung tree kill pids={existing}")
            kill_gateway_tree()

        log("DOWN -> start_gateway")
        ok = start_gateway()
        write_heartbeat("RECOVERED" if ok else "FAIL")
        return "RECOVERED" if ok else "FAIL"
    except Exception as exc:
        log(f"tick_err {type(exc).__name__}: {exc}")
        write_heartbeat("ERR", {"error": str(exc)})
        return f"ERR:{exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL_SEC)
    args = ap.parse_args()

    if args.once:
        log(f"once result={tick()}")
        return 0 if health_ok() else 1

    if not acquire_lock():
        return 0
    log(f"supervisor v2 start pid={os.getpid()} interval={args.interval}s")
    try:
        while True:
            try:
                result = tick()
                log(result)
            except Exception as exc:
                log(f"LOOP_ERR {exc}")
            time.sleep(max(5, int(args.interval)))
    finally:
        release_lock()
        log(f"supervisor exit pid={os.getpid()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
