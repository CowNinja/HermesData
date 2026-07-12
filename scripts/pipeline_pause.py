#!/usr/bin/env python3
"""Image pipeline pause gate — sovereign router phase can block Comfy auto-start."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PAUSE_PATH = Path(r"D:\HermesData\state\image-pipeline-pause.json")
VRAM_PATH = Path(r"D:\HermesData\state\vram-priority.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_pause_state() -> Dict[str, Any]:
    if not PAUSE_PATH.is_file():
        return {"paused": False}
    try:
        data = json.loads(PAUSE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"paused": False}
    except Exception:
        return {"paused": False}


def silo_primary_active() -> bool:
    if not VRAM_PATH.is_file():
        return False
    try:
        data = json.loads(VRAM_PATH.read_text(encoding="utf-8-sig"))
        return bool(data.get("silo_primary")) and str(data.get("mode", "")).lower() == "text"
    except Exception:
        return False


def image_pipeline_paused() -> bool:
    return bool(load_pause_state().get("paused"))


def image_generate_allowed(*, force: bool = False) -> bool:
    """True when Hermes image_generate / Comfy bootstrap may run."""
    if force:
        return True
    return not image_pipeline_paused()


def image_delivery_allowed() -> bool:
    """True when comfy_delivery_daemon may post PNGs to Discord."""
    return not image_pipeline_paused()


def set_image_pipeline_paused(
    paused: bool,
    *,
    reason: str = "",
    note: str = "",
) -> Dict[str, Any]:
    PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "paused": bool(paused),
        "reason": reason or ("sovereign_router_phase" if paused else "operator_resume"),
        "note": note,
        "updated_at": _utc_now(),
    }
    PAUSE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Image pipeline pause gate")
    parser.add_argument("action", nargs="?", choices=("status", "pause", "resume"), default="status")
    parser.add_argument("--reason", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    if args.action == "pause":
        state = set_image_pipeline_paused(True, reason=args.reason or "operator_pause", note=args.note)
    elif args.action == "resume":
        if silo_primary_active() and args.reason in ("comfy_stack_start", ""):
            state = set_image_pipeline_paused(
                True,
                reason="silo_primary",
                note="resume blocked — run .\\Phronesis.ps1 vram image first",
            )
        else:
            state = set_image_pipeline_paused(
                False, reason=args.reason or "operator_resume", note=args.note
            )
    else:
        state = load_pause_state()
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())