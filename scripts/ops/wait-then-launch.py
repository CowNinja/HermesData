#!/usr/bin/env python3
"""Wait for batch lock/session to clear, then run a launch script."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\HermesData")
LOCK = ROOT / "state" / "rp-batch-launch.lock"
SESSION = ROOT / "state" / "comfy-batch-session.json"
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"


def session_active() -> bool:
    if not SESSION.is_file():
        return False
    try:
        data = json.loads(SESSION.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(data.get("active"))


def wait_clear(poll_sec: float = 20.0) -> None:
    print("Waiting for batch lock/session to clear...", flush=True)
    while LOCK.is_file() or session_active():
        progress = ""
        if SESSION.is_file():
            try:
                data = json.loads(SESSION.read_text(encoding="utf-8"))
                bh = data.get("batch_health") or {}
                progress = str(bh.get("progress") or data.get("delivered_count") or "")
            except Exception:
                pass
        print(f"  still running {progress}".strip(), flush=True)
        time.sleep(poll_sec)
    print("Batch slot free.", flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: wait-then-launch.py <launch-script.py>", file=sys.stderr)
        return 2
    target = Path(sys.argv[1])
    if not target.is_file():
        print(f"missing launch script: {target}", file=sys.stderr)
        return 2
    wait_clear()
    print(f"Launching {target.name}...", flush=True)
    return subprocess.call([str(PY), str(target)])


if __name__ == "__main__":
    raise SystemExit(main())