#!/usr/bin/env python3
"""Launch 4-frame rotating harem trio — kitchen island (user OOC, cast enriched)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\HermesData")
BATCH = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\batch-rp-series.py")
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
INBOUND = ROOT / "state" / "rp-last-inbound.json"

PROMPT = (
    "OOC: series of 4, wide angle full body rear shot from behind, 3 different harem girls "
    "bent face-down over a brightly lit modern kitchen island, French kissing with tongues, "
    "lust-filled eyes looking back at viewer, both hands spreading ass cheeks wide. "
    "Wearing only: 2-inch white strapless tube tops barely covering nipples on huge perky breasts; "
    "tiny separate red plaid front and back flaps on pink hip bow strings, bare gap between flaps; "
    "black lace-top thigh-high fishnets. Nothing else."
)


def main() -> int:
    INBOUND.write_text(
        json.dumps({"text": PROMPT, "source": "kitchen_harem_trio4", "at": "2026-07-06"}, indent=2),
        encoding="utf-8",
    )
    spec = {"batch_count": 4, "group_size": 3, "batch_recipe": "user_cast_series", "fresh": True}
    cmd = [
        str(PY),
        "-u",
        str(BATCH),
        "--spec-json",
        json.dumps(spec, ensure_ascii=False),
        PROMPT,
        "--total",
        "4",
        "--recipe",
        "user_cast_series",
    ]
    print("LAUNCH:", PROMPT)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())