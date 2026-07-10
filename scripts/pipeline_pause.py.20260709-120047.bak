#!/usr/bin/env python3
"""Image pipeline pause gate — sovereign router phase can block Comfy auto-start."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PAUSE_PATH = Path(r"D:\HermesData\state\image-pipeline-pause.json")


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


def image_pipeline_paused() -> bool:
    return bool(load_pause_state().get("paused"))


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