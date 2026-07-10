#!/usr/bin/env python3
"""8091 sovereign proxy preflight — venv-owned health before gateway/Discord dispatch."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from windows_subprocess import hidden_powershell_command, run_hidden  # noqa: E402

PROXY_HEALTH = "http://127.0.0.1:8091/health"
ROUTER_MODELS = "http://127.0.0.1:8090/v1/models"
START_SCRIPT = Path(r"D:\HermesData\scripts\Start-Sovereign-Proxy-8091.ps1")
START_LLAMA = Path(r"D:\HermesData\scripts\ops\02-start-llama.ps1")
ONE_BUTTON = Path(r"D:\HermesData\scripts\Phronesis-OneButton-Start.ps1")
FORK_GUARD = Path(r"D:\HermesData\scripts\Phronesis-ForkGuard.ps1")
MIN_VRAM_FREE_MB = 9000
MAX_RETRIES = 2
RETRY_PAUSE_SEC = 5


def _powershell(cmd: str, timeout: int = 60) -> bool:
    try:
        r = run_hidden(
            hidden_powershell_command(cmd),
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


def _router_healthy(timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(ROUTER_MODELS, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _vram_free_mb() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().splitlines()[0].strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        pass
    return 0


def _start_router() -> bool:
    free = _vram_free_mb()
    if free and free < MIN_VRAM_FREE_MB:
        return False
    if START_LLAMA.is_file():
        return _powershell(f"& '{START_LLAMA}'", timeout=180)
    if ONE_BUTTON.is_file():
        return _powershell(
            f"& '{ONE_BUTTON}' -SkipGateway -SkipDashboard -SkipWorkspace -SkipSmoke",
            timeout=240,
        )
    return False


def ensure_sovereign_router(timeout: float = 3.0) -> bool:
    """Qwythos brain on 8090 — proxy is useless without it."""
    if _router_healthy(timeout):
        return True
    free = _vram_free_mb()
    if free and free < MIN_VRAM_FREE_MB:
        yield_text = Path(r"D:\HermesData\scripts\Phronesis-Yield-VRAM-For-Text.ps1")
        if yield_text.is_file():
            _powershell(f"& '{yield_text}' -Quiet", timeout=60)
    if not _start_router():
        return False
    for _ in range(30):
        if _router_healthy(timeout):
            return True
        time.sleep(2)
    return _router_healthy(timeout)


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


def ensure_sovereign_stack(timeout: float = 3.0) -> bool:
    """8090 brain first, then 8091 proxy. Both required for Discord dispatch."""
    return ensure_sovereign_router(timeout) and ensure_sovereign_proxy(timeout)


if __name__ == "__main__":
    raise SystemExit(0 if ensure_sovereign_stack() else 1)