#!/usr/bin/env python3
"""Launch 7-girl harem solo batch with outfit from rp-last-inbound (no PS JSON mangling)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\HermesData")
INBOUND = ROOT / "state" / "rp-last-inbound.json"
BATCH = Path(r"D:\PhronesisVault\Roleplay-Sandbox\sandbox\batch-rp-series.py")
PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"


def main() -> int:
    inbound = json.loads(INBOUND.read_text(encoding="utf-8-sig"))
    text = str(inbound.get("text") or "").strip()
    if not text:
        print("ERROR: no text in rp-last-inbound.json", file=sys.stderr)
        return 1
    spec = {
        "batch_count": 7,
        "batch_recipe": "harem_solo",
        "fresh": True,
        "_inbound_text": text,
    }
    cmd = [
        str(PY),
        "-u",
        str(BATCH),
        "--spec-json",
        json.dumps(spec, ensure_ascii=False),
        "OOC: series of 7 images, one of each harem member",
        "--total",
        "7",
        "--recipe",
        "harem_solo",
    ]
    print("LAUNCH:", " ".join(cmd[:4]), "...")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())