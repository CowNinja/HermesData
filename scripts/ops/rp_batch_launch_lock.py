"""Prevent duplicate batch-rp-series processes with the same series signature."""
from __future__ import annotations

import ctypes
import json
import os
import time
from pathlib import Path

LOCK_FILE = Path(r"D:\HermesData\state\rp-batch-launch.lock")
STALE_SEC = 7200


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = ctypes.windll.kernel32.OpenProcess(access, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def make_signature(
    *,
    recipe: str,
    total: int,
    offset: int = 0,
    limit: int = 0,
    script: str = "batch-rp-series",
) -> str:
    return f"{script}|{recipe}|{total}|{offset}|{limit}"


def read_lock() -> dict:
    if not LOCK_FILE.is_file():
        return {}
    try:
        data = json.loads(LOCK_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_lock(payload: dict) -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCK_FILE.with_suffix(".lock.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(LOCK_FILE)


def check_running(signature: str = "") -> dict:
    """Return lock info if an alive process holds the lock (optionally same signature)."""
    data = read_lock()
    if not data:
        return {"running": False}
    pid = int(data.get("pid") or 0)
    sig = str(data.get("signature") or "")
    started = float(data.get("started_at_ts") or 0)
    stale = started > 0 and (time.time() - started) > STALE_SEC
    alive = _pid_alive(pid) and not stale
    if not alive:
        return {"running": False, "stale": bool(data), "prior": data}
    if signature and sig != signature:
        return {"running": True, "different_signature": True, "signature": sig, "pid": pid}
    return {"running": True, "signature": sig, "pid": pid, "started_at": data.get("started_at")}


def acquire(signature: str) -> tuple[bool, dict]:
    existing = check_running()
    if existing.get("running"):
        if existing.get("different_signature"):
            return False, {"reason": "other_batch_running", **existing}
        if str(existing.get("signature") or "") == signature:
            return False, {"reason": "duplicate_batch", **existing}
        return False, {"reason": "batch_lock_held", **existing}
    if existing.get("stale"):
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    payload = {
        "pid": os.getpid(),
        "signature": signature,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "started_at_ts": time.time(),
    }
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_FILE.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2))
        return True, payload
    except FileExistsError:
        again = check_running(signature)
        if again.get("running") and str(again.get("signature") or "") == signature:
            return False, {"reason": "duplicate_batch", **again}
        return False, {"reason": "lock_race", **again}


def release(signature: str = "") -> None:
    data = read_lock()
    if not data:
        return
    if signature and str(data.get("signature") or "") != signature:
        return
    if int(data.get("pid") or 0) != os.getpid():
        return
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass