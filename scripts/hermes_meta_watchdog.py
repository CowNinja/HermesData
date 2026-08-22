#!/usr/bin/env python3
"""Meta-watchdog v2: keep hermes_gateway_SERVICE alive (Red-style outer loop).

Does NOT start gateway.run directly (avoids dual-start races).

2026-08-11: also when-down ensure sovereign proxy :8091 (RP + local primary path).
Gateway-only heal left RP dead while :8642 stayed GREEN.
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
# Cooldown between proxy ensure attempts (matches ensure_single_proxy restart gate)
PROXY_ENSURE_COOLDOWN_S = 90.0
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
BREAKAWAY = 0x01000000
VENV_PYW = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
VENV_PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
ENSURE_PROXY = SCRIPTS / "ensure_single_proxy_8091.py"
_last_proxy_ensure_mono = 0.0


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def pid_alive(pid: int) -> bool:
    """Silent OpenProcess — never tasklist (tasklist was flashing STT every 15s)."""
    if pid <= 0:
        return False
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        # ERROR_ACCESS_DENIED (5) usually means process exists
        return ctypes.windll.kernel32.GetLastError() == 5
    except Exception:
        return False


def service_alive() -> bool:
    """Prefer lock PID; fallback Toolhelp snapshot (no powershell/tasklist spawn)."""
    if SVC_LOCK.is_file():
        try:
            pid = int(SVC_LOCK.read_text(encoding="utf-8").strip().split()[0])
            if pid_alive(pid):
                return True
        except Exception:
            pass
    # Silent: if any process image is pythonw and we still hold lock file stale,
    # try Toolhelp by name only is weak — re-read lock once more after 0.2s.
    try:
        time.sleep(0.05)
        if SVC_LOCK.is_file():
            pid = int(SVC_LOCK.read_text(encoding="utf-8").strip().split()[0])
            return pid_alive(pid)
    except Exception:
        pass
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


def health_proxy() -> bool:
    """Sovereign MoE proxy :8091 — required for RP + local primary routing."""
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:8091/health",
            headers={"User-Agent": "meta-watchdog/2.1-proxy"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def ensure_proxy_when_down() -> None:
    """When-down only: kitchen helper ensure_single_proxy_8091 (cooldown)."""
    global _last_proxy_ensure_mono
    if health_proxy():
        return
    now = time.monotonic()
    if (now - _last_proxy_ensure_mono) < PROXY_ENSURE_COOLDOWN_S:
        log("proxy :8091 DOWN (ensure cooldown active)")
        return
    if not ENSURE_PROXY.is_file():
        log("proxy :8091 DOWN but ensure_single_proxy_8091.py missing")
        return
    _last_proxy_ensure_mono = now
    py = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    log("proxy :8091 DOWN -> ensure_single_proxy_8091.py")
    try:
        r = subprocess.run(
            [py, str(ENSURE_PROXY), "--json"],
            cwd=str(SCRIPTS),
            timeout=200,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        up = health_proxy()
        tail = ((r.stdout or "") + (r.stderr or ""))[-240:].replace("\n", " ")
        log(f"proxy ensure rc={r.returncode} up={up} tail={tail}")
    except Exception as exc:
        log(f"proxy ensure err: {exc}")


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


def _kitchen_quiet() -> bool:
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import kitchen_quiet as kq

        return bool(kq.is_quiet())
    except Exception:
        return any(
            (STATE / n).is_file()
            for n in ("hermes_update.IN_PROGRESS", "hermes_ops_quiet.ON")
        )


def main() -> int:
    if not acquire():
        return 0
    log(
        f"meta-watchdog v2.1 start pid={os.getpid()} "
        f"(gateway-service + when-down :8091 proxy)"
    )
    try:
        while True:
            try:
                if _kitchen_quiet():
                    log("quiet: skip restart (Safe-Update park)")
                    time.sleep(INTERVAL)
                    continue
                if not service_alive():
                    log("gateway-service DEAD -> restart")
                    start_service()
                    time.sleep(10)
                else:
                    # Measure gateway + proxy; ensure proxy only when-down
                    ensure_proxy_when_down()
                    log(
                        f"OK service_alive=True gateway_health={health()} "
                        f"proxy_8091={health_proxy()}"
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
