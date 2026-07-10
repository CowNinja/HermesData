#!/usr/bin/env python3
"""Launch 7 solo harem portraits — nude, rear view, hands-and-knees ass spread."""
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
    "OOC: series of 7, one of each harem member, completely nude, "
    "camera shot from behind, on hands and knees, "
    "both hands spreading plump ass cheeks wide, exposed pussy and visible asshole, no panties, "
    "rear view full body, looking back at viewer."
)


def main() -> int:
    INBOUND.write_text(
        json.dumps({"text": PROMPT, "source": "harem7_nude_spread", "at": "2026-07-06"}, indent=2),
        encoding="utf-8",
    )
    spec = {"batch_count": 7, "group_size": 1, "batch_recipe": "user_cast_series", "fresh": True}
    cmd = [
        str(PY),
        "-u",
        str(BATCH),
        "--spec-json",
        json.dumps(spec, ensure_ascii=False),
        PROMPT,
        "--total",
        "7",
        "--recipe",
        "user_cast_series",
    ]
    print("LAUNCH:", PROMPT)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())