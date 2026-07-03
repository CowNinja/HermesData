#!/usr/bin/env python3
"""8091 sovereign proxy preflight — venv-owned health before gateway/Discord dispatch."""
from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PROXY_HEALTH = "http://127.0.0.1:8091/health"
START_SCRIPT = Path(r"D:\HermesData\scripts\Start-Sovereign-Proxy-8091.ps1")
FORK_GUARD = Path(r"D:\HermesData\scripts\Phronesis-ForkGuard.ps1")
MAX_RETRIES = 2
RETRY_PAUSE_SEC = 5


def _powershell(cmd: str, timeout: int = 60) -> bool:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _venv_owns_8091() -> bool:
    if not FORK_GUARD.is_file():
        return _proxy_healthy()
    return _powershell(f". '{FORK_GUARD}'; Test-VenvOwns8091", timeout=15)


def _fork_guard() -> None:
    if FORK_GUARD.is_file():
        _powershell(f". '{FORK_GUARD}'; Ensure-VenvProxyOnly | Out-Null", timeout=30)


def _proxy_healthy(timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(PROXY_HEALTH, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return "GREEN" in body or "YELLOW" in body
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _start_proxy() -> bool:
    if not START_SCRIPT.is_file():
        return False
    return _powershell(
        f"& '{START_SCRIPT}'",
        timeout=120,
    )


def ensure_sovereign_proxy(timeout: float = 3.0) -> bool:
    """ForkGuard + venv-owned 8091 with retries. Returns True when healthy."""
    for attempt in range(MAX_RETRIES + 1):
        _fork_guard()
        if _venv_owns_8091():
            return True
        if _start_proxy() and _venv_owns_8091():
            return True
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_PAUSE_SEC)
    return _venv_owns_8091()


if __name__ == "__main__":
    raise SystemExit(0 if ensure_sovereign_proxy() else 1)