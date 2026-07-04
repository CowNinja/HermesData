#!/usr/bin/env python3
"""Monitor Comfy output + gallery for new PNGs and trigger delivery ticks."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUTPUT = Path(r"D:\ComfyUI\output")
GALLERY = Path(r"D:\ComfyUI\gallery\images")
DAEMON = Path(r"D:\HermesData\scripts\comfy_delivery_daemon.py")
LOG = Path(r"D:\HermesData\logs\comfy-delivery-watch.log")
DEFAULT_CHANNEL = "1521146755985576116"
POLL_SEC = 5


def _snapshot() -> dict[str, float]:
    snap: dict[str, float] = {}
    for root in (OUTPUT, GALLERY):
        if not root.is_dir():
            continue
        for path in root.glob("*.png"):
            try:
                snap[str(path)] = path.stat().st_mtime
            except OSError:
                pass
    return snap


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _daemon_active() -> bool:
    lock = Path(r"D:\HermesData\state\comfy-delivery-daemon.lock")
    if not lock.is_file():
        return False
    try:
        pid = int(lock.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    return _pid_alive(pid)


def _ensure_daemon(channel: str) -> None:
    lock = Path(r"D:\HermesData\state\comfy-delivery-daemon.lock")
    pid = 0
    if lock.is_file():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except Exception:
            pid = 0
    if _pid_alive(pid):
        return
    ps1 = Path(r"D:\HermesData\scripts\ops\Ensure-RP-Watchers.ps1")
    if ps1.is_file():
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-Channel", channel, "-Quiet"],
            timeout=30,
            check=False,
        )
        _log("ENSURE daemon restarted")


def _tick(channel: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(DAEMON), "--once", "--channel", channel],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (proc.stdout or "").strip()
    if out:
        try:
            return json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            return {"raw": out, "rc": proc.returncode}
    return {"rc": proc.returncode, "stderr": (proc.stderr or "")[:200]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--poll", type=int, default=POLL_SEC)
    args = parser.parse_args()

    prev = _snapshot()
    out_n = len(list(OUTPUT.glob("standard__*.png")))
    gal_n = len(list(GALLERY.glob("*.png")))
    _log(f"watch start output={out_n} gallery={gal_n} channel={args.channel}")
    last_ensure = 0.0
    while True:
        now = time.time()
        if now - last_ensure >= 60:
            _ensure_daemon(args.channel)
            last_ensure = now
        cur = _snapshot()
        new_paths = [p for p, mt in cur.items() if p not in prev or prev[p] < mt]
        if new_paths:
            for p in sorted(new_paths):
                name = Path(p).name
                if _daemon_active():
                    _log(f"NEW {name} (daemon delivers)")
                else:
                    _log(f"NEW {name}")
            if not _daemon_active():
                result = _tick(args.channel)
                _log(f"TICK {json.dumps(result)}")
        prev = cur
        time.sleep(max(2, args.poll))


if __name__ == "__main__":
    raise SystemExit(main())