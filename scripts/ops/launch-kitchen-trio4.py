#!/usr/bin/env python3
"""Launch 4-image anonymous kitchen trio batch (no stale inbound pollution)."""
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
    "OOC: series of 4 images, three darkly tanned Arabian voluptuous supermodel brunettes, "
    "wearing only glasses and skimpy halter tops and extremely short skirts, bending face first "
    "over a brightly lit kitchen island counter, both hands reaching back and spreading plump ass "
    "cheeks, passionately kissing each other while looking back directly at the viewer/camera."
)


def main() -> int:
    INBOUND.write_text(
        json.dumps({"text": PROMPT, "source": "kitchen_trio4_test", "at": "2026-07-06"}, indent=2),
        encoding="utf-8",
    )
    spec = {
        "batch_count": 4,
        "group_size": 3,
        "batch_recipe": "freeform_series",
        "fresh": True,
    }
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
        "freeform_series",
    ]
    print("LAUNCH:", PROMPT[:80], "...")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())