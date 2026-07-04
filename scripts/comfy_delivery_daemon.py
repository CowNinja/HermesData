#!/usr/bin/env python3
"""Poll Comfy output and auto-post new PNGs to the Alice roleplay Discord thread."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from windows_subprocess import prefer_pythonw, run_hidden  # noqa: E402

COMFY_OUTPUT = Path(r"D:\ComfyUI\output")
STATE_FILE = Path(r"D:\HermesData\state\comfy-delivery-daemon.json")
LOCK_FILE = Path(r"D:\HermesData\state\comfy-delivery-daemon.lock")
DEFAULT_CHANNEL = "1521146755985576116"
POST_SCRIPT = SCRIPTS.parent / "temp" / "post_discord_image.py"
POLL_SEC = 3


def _load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_name": "", "last_mtime": 0.0, "delivered": [], "delivered_sha256": []}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _newest_png() -> tuple[str, float] | None:
    best_name = ""
    best_mtime = 0.0
    for path in COMFY_OUTPUT.glob("standard__*.png"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best_name = path.name
    if not best_name:
        return None
    return best_name, best_mtime


def _deliver(channel: str, png_name: str) -> bool:
    png_path = COMFY_OUTPUT / png_name
    if not png_path.is_file():
        return False
    caption = f"Auto-deliver: {png_name}"
    proc = run_hidden(
        [prefer_pythonw(sys.executable), str(POST_SCRIPT), channel, str(png_path), caption],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return proc.returncode == 0


def tick(channel: str = DEFAULT_CHANNEL) -> dict:
    state = _load_state()
    current = _newest_png()
    if not current:
        return {"action": "none", "reason": "no_png"}
    name, mtime = current
    if name == state.get("last_name") and mtime <= float(state.get("last_mtime") or 0):
        return {"action": "none", "reason": "unchanged", "png": name}
    delivered = list(state.get("delivered") or [])
    delivered_sha = list(state.get("delivered_sha256") or [])
    png_path = COMFY_OUTPUT / name
    digest = _sha256_file(png_path) if png_path.is_file() else ""
    if name in delivered or (digest and digest in delivered_sha):
        state["last_name"] = name
        state["last_mtime"] = mtime
        _save_state(state)
        return {"action": "none", "reason": "already_delivered", "png": name, "sha256": digest[:12]}
    ok = _deliver(channel, name)
    if ok:
        delivered.append(name)
        if digest:
            delivered_sha.append(digest)
        state["delivered"] = delivered[-50:]
        state["delivered_sha256"] = delivered_sha[-50:]
        state["last_name"] = name
        state["last_mtime"] = mtime
        _save_state(state)
    return {"action": "deliver", "ok": ok, "png": name}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Comfy output delivery daemon")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=POLL_SEC)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(tick(args.channel)))
        return 0
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = LOCK_FILE.open("x", encoding="utf-8")
        lock_fd.write(str(os.getpid()))
        lock_fd.close()
    except FileExistsError:
        print(json.dumps({"error": "daemon_already_running"}))
        return 0
    while True:
        try:
            result = tick(args.channel)
            if result.get("action") == "deliver":
                print(json.dumps(result), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())