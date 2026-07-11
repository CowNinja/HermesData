#!/usr/bin/env python3
"""Harem 7 — partial outfit (crop top + jeans at thighs) with exposed genitals."""
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
    "OOC: series of 7, one of each harem member, camera from behind, on hands and knees, "
    "both hands spreading ass cheeks wide open, exposed pussy and visible asshole, no panties, no underwear. "
    "Wearing ONLY the following: skimpy 1-inch crop tops barely covering nipples; "
    "tight jeans pulled down and bunched around upper thighs only — "
    "bare ass, bare pussy, and bare asshole fully exposed between crop top and jeans, "
    "jeans must NOT cover crotch or pussy."
)


def main() -> int:
    INBOUND.write_text(
        json.dumps({"text": PROMPT, "source": "harem7_exposed_partial", "at": "2026-07-06"}, indent=2),
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