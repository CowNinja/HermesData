#!/usr/bin/env python3
"""Script-only gate for zero-newline corruption (cron-friendly).

Silent (empty stdout, exit 0) when clean.
Prints a short alert + non-zero exit when corrupt files found.
Optional --restore uses hygiene_zero_newline_scripts restore path.

Usage:
  python script_newline_integrity_gate.py
  python script_newline_integrity_gate.py --restore
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HYGIENE = Path(r"D:\HermesData\scripts\hygiene_zero_newline_scripts.py")
LOG = Path(r"D:\PhronesisVault\Operations\logs\script-newline-integrity.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--min-bytes", type=int, default=500)
    args = ap.parse_args()

    cmd = [sys.executable, str(HYGIENE), "--json", "--min-bytes", str(args.min_bytes)]
    if args.restore:
        cmd.append("--restore")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    raw = (proc.stdout or "").strip()
    try:
        payload = json.loads(raw) if raw else {"corrupt_count": -1, "error": "no json"}
    except json.JSONDecodeError:
        payload = {"corrupt_count": -1, "error": "bad json", "stdout": raw[:500]}

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

    count = int(payload.get("corrupt_count") or 0)
    if count <= 0 and "error" not in payload:
        return 0  # silent clean

    # Alert only when broken
    names = payload.get("corrupt") or []
    print(f"ALERT zero-newline scripts: {count}")
    for n in names[:20]:
        print(f"  - {n}")
    if payload.get("restore"):
        print("restore:", json.dumps(payload.get("restore")))
    return 1 if count > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
