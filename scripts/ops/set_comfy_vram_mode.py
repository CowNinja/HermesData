#!/usr/bin/env python3
"""Flip Comfy VRAM launch mode for batch windows (lowvram vs ram_prefer)."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VRAM_MODE_FILE = ROOT / "state" / "comfy-vram-mode.json"
BATCH_VRAM_SNAPSHOT = ROOT / "state" / "comfy-batch-vram-snapshot.json"

MODE_NOTES = {
    "lowvram": "Comfy launches with lowvram (default balance, faster staging)",
    "ram_prefer": "Comfy launches with novram + disable-smart-memory (heavier RAM staging, slower renders)",
}

# Named profiles for batch session + Hermes visibility (Swiss-army-knife layer).
VRAM_PROFILES: dict[str, dict[str, str]] = {
    "batch_default": {"mode": "lowvram", "batch_speed": "quality", "notes": "default multi-frame batch"},
    "triplet_smoke": {"mode": "lowvram", "batch_speed": "quality", "notes": "3-girl groups, no hand detailer"},
    "group_4plus": {"mode": "lowvram", "batch_speed": "quality", "notes": "4+ subjects, count-lock poses"},
    "solo_max_quality": {"mode": "ram_prefer", "batch_speed": "quality", "notes": "single portrait max VRAM"},
}

PROFILE_FILE = ROOT / "state" / "comfy-vram-profile.json"


def read_mode() -> str:
    if not VRAM_MODE_FILE.is_file():
        return "lowvram"
    try:
        data = json.loads(VRAM_MODE_FILE.read_text(encoding="utf-8-sig"))
        mode = str(data.get("mode") or "lowvram").strip()
        return mode if mode in MODE_NOTES else "lowvram"
    except Exception:
        return "lowvram"


def write_mode(mode: str, *, notes: str = "") -> dict:
    mode = mode if mode in MODE_NOTES else "lowvram"
    payload = {
        "mode": mode,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "notes": notes or MODE_NOTES[mode],
    }
    VRAM_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    VRAM_MODE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def read_profile() -> dict:
    if not PROFILE_FILE.is_file():
        return {}
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_vram_profile(profile: str) -> dict:
    """Apply a named VRAM profile; writes profile JSON for batch session sync."""
    key = str(profile or "batch_default").strip().lower()
    spec = VRAM_PROFILES.get(key) or VRAM_PROFILES["batch_default"]
    mode = spec.get("mode") or "lowvram"
    payload = {
        "profile": key,
        "mode": mode,
        "batch_speed": spec.get("batch_speed") or "quality",
        "notes": spec.get("notes") or "",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if mode != read_mode():
        write_mode(mode, notes=f"profile:{key} - {payload['notes']}")
    return {"ok": True, **payload}


def begin_batch_optimize(profile: str = "") -> dict:
    """Save current mode and switch to lowvram for active batch window."""
    if str(os.environ.get("RP_BATCH_VRAM_OPTIMIZE", "1")).strip().lower() in ("0", "false", "no"):
        return {"ok": True, "skipped": True, "reason": "RP_BATCH_VRAM_OPTIMIZE=0"}
    prof = {}
    if profile:
        prof = set_vram_profile(profile)
    elif read_profile().get("profile"):
        prof = read_profile()
    prior = read_mode()
    if BATCH_VRAM_SNAPSHOT.is_file():
        try:
            snap = json.loads(BATCH_VRAM_SNAPSHOT.read_text(encoding="utf-8-sig"))
            if isinstance(snap, dict) and snap.get("prior_mode"):
                prior = str(snap["prior_mode"])
        except Exception:
            pass
    else:
        BATCH_VRAM_SNAPSHOT.write_text(
            json.dumps(
                {
                    "prior_mode": prior,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    active = "lowvram"
    changed = prior != active
    if changed:
        write_mode(active, notes="batch window - lowvram for faster GPU staging")
    out = {"ok": True, "prior_mode": prior, "active_mode": active, "changed": changed}
    if prof:
        out["profile"] = prof.get("profile")
    return out


def end_batch_restore() -> dict:
    """Restore VRAM mode saved at batch start."""
    if not BATCH_VRAM_SNAPSHOT.is_file():
        return {"ok": True, "skipped": True, "reason": "no_snapshot"}
    try:
        snap = json.loads(BATCH_VRAM_SNAPSHOT.read_text(encoding="utf-8-sig"))
    except Exception:
        BATCH_VRAM_SNAPSHOT.unlink(missing_ok=True)
        return {"ok": False, "error": "invalid_snapshot"}
    prior = str(snap.get("prior_mode") or "lowvram")
    write_mode(prior, notes=MODE_NOTES.get(prior, MODE_NOTES["lowvram"]))
    BATCH_VRAM_SNAPSHOT.unlink(missing_ok=True)
    return {"ok": True, "restored_mode": prior}


def main() -> int:
    parser = argparse.ArgumentParser(description="Comfy VRAM mode helper for batch windows")
    parser.add_argument("--read", action="store_true", help="Print current mode JSON")
    parser.add_argument("--set", metavar="MODE", help="lowvram | ram_prefer")
    parser.add_argument("--batch-begin", action="store_true", help="Optimize for batch (lowvram)")
    parser.add_argument("--batch-end", action="store_true", help="Restore mode after batch")
    parser.add_argument("--profile", metavar="NAME", help="triplet_smoke | group_4plus | solo_max_quality | batch_default")
    args = parser.parse_args()

    if args.profile:
        print(json.dumps(set_vram_profile(args.profile)))
        return 0
    if args.batch_begin:
        print(json.dumps(begin_batch_optimize(profile=args.profile or "")))
        return 0
    if args.batch_end:
        print(json.dumps(end_batch_restore()))
        return 0
    if args.set:
        print(json.dumps(write_mode(args.set.strip())))
        return 0
    print(json.dumps({"mode": read_mode(), "file": str(VRAM_MODE_FILE)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())