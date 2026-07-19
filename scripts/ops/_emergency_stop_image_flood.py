#!/usr/bin/env python3
"""Emergency stop: pause image pipeline, kill delivery posters, seal backlog."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\HermesData")
STATE = ROOT / "state"
SCRIPTS = ROOT / "scripts"
PAUSE = STATE / "image-pipeline-pause.json"
BATCH = STATE / "comfy-batch-session.json"
LOCK = STATE / "comfy-delivery-daemon.lock"
TICK = STATE / "comfy-delivery-tick.lock"

PATTERNS = (
    "watch_comfy_delivery",
    "comfy_delivery_daemon",
    "post_discord_image",
    "Ensure-RP-Watchers",
    "comfy_gallery_refresh",
)


def _kill_matching() -> list[int]:
    killed: list[int] = []
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and ("
        + " -or ".join(f"$_.CommandLine -like '*{p}*'" for p in PATTERNS)
        + ") } | Select-Object -ExpandProperty ProcessId"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            errors="ignore",
            timeout=30,
        )
    except Exception as exc:
        print(json.dumps({"kill_scan_error": str(exc)}))
        return killed
    for tok in raw.split():
        if not tok.isdigit():
            continue
        pid = int(tok)
        if pid == os.getpid():
            continue
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            killed.append(pid)
            print(f"killed {pid}")
        except Exception as exc:
            print(f"kill_fail {pid}: {exc}")
    return killed


def _pause() -> dict:
    # Prefer pipeline_pause helper so hard-stop semantics stay consistent.
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from pipeline_pause import set_image_pipeline_paused  # type: ignore

        return set_image_pipeline_paused(
            True,
            reason="emergency_discord_image_flood",
            note="HARD-STOP channel 1524821864956956793; do not auto-resume; delivery sealed",
            hard=True,
        )
    except Exception:
        state = {
            "paused": True,
            "reason": "emergency_discord_image_flood",
            "note": "HARD-STOP channel 1524821864956956793; do not auto-resume; delivery sealed",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hard": True,
            "paused_by": "grok_emergency",
        }
        PAUSE.parent.mkdir(parents=True, exist_ok=True)
        PAUSE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state


def _halt_batch() -> None:
    if not BATCH.is_file():
        return
    try:
        b = json.loads(BATCH.read_text(encoding="utf-8-sig"))
    except Exception:
        return
    if not isinstance(b, dict):
        return
    b["active"] = False
    b["halted_reason"] = "emergency_flood_stop"
    b["halted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    BATCH.write_text(json.dumps(b, indent=2), encoding="utf-8")
    print("batch_halted")


def _seal_all() -> dict:
    sys.path.insert(0, str(SCRIPTS))
    from comfy_delivery_daemon import (  # type: ignore
        _load_state,
        _seal_existing_pngs,
    )

    before = _load_state()
    after = _seal_existing_pngs(before)
    return {
        "before_last": before.get("last_name"),
        "before_mtime": before.get("last_mtime"),
        "before_delivered_n": len(before.get("delivered") or []),
        "after_last": after.get("last_name"),
        "after_mtime": after.get("last_mtime"),
        "after_delivered_n": len(after.get("delivered") or []),
    }


def main() -> int:
    killed = _kill_matching()
    for lock in (LOCK, TICK):
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass
    pause = _pause()
    _halt_batch()
    seal = {}
    try:
        seal = _seal_all()
    except Exception as exc:
        seal = {"error": str(exc)}
    out = {"killed": killed, "pause": pause, "seal": seal}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
