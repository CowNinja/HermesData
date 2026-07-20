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


# Auto-resume reasons that must not clear operator/emergency hard-stops.
_AUTO_RESUME_REASONS = frozenset(
    {
        "comfy_stack_start",
        "vram_image_mode",
        "operator_resume",
        "",
    }
)
_HARD_PAUSE_REASON_PREFIXES = (
    "emergency_",
    "hard_stop",
    "discord_flood",
    "operator_hard",
)


def is_hard_pause(state: Dict[str, Any] | None = None) -> bool:
    """True when pause must not be cleared by Comfy-Stack / VRAM auto-resume."""
    st = state if isinstance(state, dict) else load_pause_state()
    if not st.get("paused"):
        return False
    if st.get("hard") or st.get("hard_stop") or st.get("lock"):
        return True
    reason = str(st.get("reason") or "").lower()
    note = str(st.get("note") or "").lower()
    if any(reason.startswith(p) for p in _HARD_PAUSE_REASON_PREFIXES):
        return True
    if "do not auto-resume" in note or "do-not-auto-resume" in note or "hard-stop" in note:
        return True
    return False


def set_image_pipeline_paused(
    paused: bool,
    *,
    reason: str = "",
    note: str = "",
    hard: bool | None = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Write pause gate.

    Provenance hard-guard (2026-07-20): when already unpaused, soft auto-resume
    callers (comfy_stack_start / vram_image_mode / empty reason) must NOT clobber
    operator reason/note. Pass force=True to intentionally rewrite provenance.
    """
    PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = load_pause_state()
    reason_s = reason or ("sovereign_router_phase" if paused else "operator_resume")

    # API-level soft-resume noop (matches CLI) — protects operator_resume sticky note.
    if (
        not force
        and not paused
        and not current.get("paused")
        and reason_s in _AUTO_RESUME_REASONS
        and reason_s != "operator_resume"
    ):
        state = dict(current)
        state["soft_resume_noop"] = reason_s or "auto"
        state["soft_resume_noop_at"] = _utc_now()
        PAUSE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state

    # Preserve non-empty operator note when unpaused→unpaused operator_resume with empty note.
    if (
        not force
        and not paused
        and not current.get("paused")
        and reason_s == "operator_resume"
        and not (note or "").strip()
        and (current.get("note") or "").strip()
    ):
        note = str(current.get("note") or "")

    if hard is None:
        hard = bool(paused) and (
            any(reason_s.lower().startswith(p) for p in _HARD_PAUSE_REASON_PREFIXES)
            or "do not auto-resume" in (note or "").lower()
            or "do-not-auto-resume" in (note or "").lower()
        )
    state = {
        "paused": bool(paused),
        "reason": reason_s,
        "note": note,
        "updated_at": _utc_now(),
        "hard": bool(hard) if paused else False,
    }
    PAUSE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Image pipeline pause gate")
    parser.add_argument("action", nargs="?", choices=("status", "pause", "resume"), default="status")
    parser.add_argument("--reason", default="")
    parser.add_argument("--note", default="")
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Hard pause: block comfy_stack_start / vram auto-resume until explicit operator resume",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="On resume: allow clearing a hard/emergency pause",
    )
    args = parser.parse_args()
    if args.action == "pause":
        state = set_image_pipeline_paused(
            True,
            reason=args.reason or "operator_pause",
            note=args.note,
            hard=True if args.hard else None,
        )
    elif args.action == "resume":
        current = load_pause_state()
        if silo_primary_active() and args.reason in ("comfy_stack_start", ""):
            state = set_image_pipeline_paused(
                True,
                reason="silo_primary",
                note="resume blocked — run .\\Phronesis.ps1 vram image first",
            )
        elif is_hard_pause(current) and not args.force and args.reason in _AUTO_RESUME_REASONS:
            # Keep hard emergency pauses; Comfy may start without re-enabling Discord delivery.
            state = dict(current)
            state["resume_blocked"] = True
            state["resume_blocked_by"] = args.reason or "auto"
            state["resume_blocked_at"] = _utc_now()
        elif (
            not current.get("paused")
            and (args.reason or "") in _AUTO_RESUME_REASONS
            and (args.reason or "") != "operator_resume"
        ):
            # Already unpaused — soft stack/vram resume must not clobber reason/note.
            state = dict(current)
            state["soft_resume_noop"] = args.reason or "auto"
            state["soft_resume_noop_at"] = _utc_now()
            PAUSE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        else:
            state = set_image_pipeline_paused(
                False, reason=args.reason or "operator_resume", note=args.note, hard=False
            )
    else:
        state = load_pause_state()
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
