#!/usr/bin/env python3
"""Scan multiple roots for zero-newline source files (report / optional restore from *.bak)."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOTS_DEFAULT = [
    Path(r"D:\HermesData\scripts"),
    Path(r"D:\PhronesisVault\scripts"),
]
EXTS = {".py", ".js", ".sh", ".yaml", ".yml", ".ts", ".ps1"}
SKIP_PARTS = {"node_modules", ".git", "__pycache__", "_corrupt", "llama.cpp", "ComfyUI"}


def scan(roots: list[Path], min_bytes: int) -> list[Path]:
    bad: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            low = str(p).lower()
            if any(s in low for s in SKIP_PARTS):
                continue
            if ".bak" in p.name.lower():
                continue
            try:
                b = p.read_bytes()
            except OSError:
                continue
            if len(b) >= min_bytes and b.count(b"\n") == 0:
                bad.append(p)
    return bad


def restore(paths: list[Path]) -> dict:
    report = {"restored": [], "failed": []}
    for p in paths:
        stash = p.parent / "_corrupt_oneline_auto"
        stash.mkdir(exist_ok=True)
        cands = sorted(p.parent.glob(p.name + "*"), key=lambda x: x.stat().st_mtime, reverse=True)
        good = None
        for c in cands:
            if c == p or c.suffix == ".md":
                continue
            try:
                if c.read_bytes().count(b"\n") > 5:
                    good = c
                    break
            except OSError:
                continue
        if not good:
            report["failed"].append(p.name)
            continue
        shutil.copy2(p, stash / p.name)
        shutil.copy2(good, p)
        report["restored"].append({"file": str(p), "from": good.name})
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--min-bytes", type=int, default=400)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    bad = scan(ROOTS_DEFAULT, args.min_bytes)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "corrupt_count": len(bad),
        "corrupt": [str(p) for p in bad],
    }
    if args.restore and bad:
        payload["restore"] = restore(bad)
        bad2 = scan(ROOTS_DEFAULT, args.min_bytes)
        payload["corrupt_count_after"] = len(bad2)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"zero-newline sources: {payload['corrupt_count']}")
        for n in payload["corrupt"][:40]:
            print(" ", n)
        if args.restore:
            print("restore:", json.dumps(payload.get("restore"), indent=2)[:2000])
    return 1 if payload["corrupt_count"] and not args.restore else 0


if __name__ == "__main__":
    raise SystemExit(main())
