#!/usr/bin/env python3
"""Detect (and optionally restore) zero-newline corrupted .py files under HermesData/scripts.

Root cause class (2026-07-10): batch rewrite stripped newlines so entire modules
became a single-line string/docstring and AST body was empty. Proxy then failed
with: cannot import name preview_route from router_bridge.

Usage:
  python hygiene_zero_newline_scripts.py              # report only
  python hygiene_zero_newline_scripts.py --restore    # restore from *.20260709-120047.bak when present
  python hygiene_zero_newline_scripts.py --min-bytes 500
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\HermesData\scripts")
BAK_SUFFIX = ".20260709-120047.bak"
DEFAULT_STASH = ROOT / "_corrupt_oneline_auto"


def scan(min_bytes: int) -> list[Path]:
    bad: list[Path] = []
    for p in sorted(ROOT.glob("*.py")):
        try:
            b = p.read_bytes()
        except OSError:
            continue
        if len(b) >= min_bytes and b.count(b"\n") == 0:
            bad.append(p)
    return bad


def restore(paths: list[Path], stash: Path) -> dict:
    stash.mkdir(parents=True, exist_ok=True)
    report = {"restored": [], "failed": [], "stash": str(stash)}
    for p in paths:
        bak = ROOT / f"{p.name}{BAK_SUFFIX}"
        if not bak.exists() or bak.read_bytes().count(b"\n") == 0:
            # try any newer bak with newlines
            cands = sorted(ROOT.glob(f"{p.name}*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)
            bak = next((c for c in cands if c.read_bytes().count(b"\n") > 0), None)
        if bak is None:
            report["failed"].append({"file": p.name, "reason": "no good bak"})
            continue
        shutil.copy2(p, stash / p.name)
        shutil.copy2(bak, p)
        report["restored"].append({"file": p.name, "from": bak.name})
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--min-bytes", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    bad = scan(args.min_bytes)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "corrupt_count": len(bad),
        "corrupt": [p.name for p in bad],
    }
    if args.restore and bad:
        payload["restore"] = restore(bad, DEFAULT_STASH)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"zero-newline corrupt .py: {len(bad)}")
        for n in payload["corrupt"]:
            print(f"  - {n}")
        if args.restore:
            print("restore:", json.dumps(payload.get("restore"), indent=2))
    return 1 if bad and not args.restore else 0


if __name__ == "__main__":
    raise SystemExit(main())
