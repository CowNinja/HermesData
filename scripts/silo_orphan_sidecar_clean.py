#!/usr/bin/env python3
"""Remove orphan silo sidecars whose primary file is gone (post bulk-rehome residue).

Safe: only deletes known sidecar suffixes when primary path does not exist.
Default dry-run. --apply deletes.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SIDES = (
    ".meta.json",
    ".context.json",
    ".train.md",
    ".ocr.md",
    ".extract.json",
    ".context.train.md",
)
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-orphan-sidecar-clean-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def primary_for(p: Path) -> Path | None:
    name = p.name
    for s in SIDES:
        if name.endswith(s):
            return p.with_name(name[: -len(s)])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/_Inbox")
    ap.add_argument("--limit", type=int, default=15000)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    root = Path(args.root)
    removed = 0
    scanned = 0
    samples = []
    if not root.is_dir():
        print(json.dumps({"error": "root missing", "root": str(root)}))
        return 1
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        scanned += 1
        prim = primary_for(p)
        if prim is None:
            continue
        if prim.is_file():
            continue
        samples.append(str(p)[:120])
        if args.apply:
            try:
                p.unlink()
                removed += 1
            except Exception:
                pass
        else:
            removed += 1  # would-remove count
        if removed >= args.limit:
            break
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"# Orphan sidecar clean — {utc()}\n\n"
        f"**Apply:** {args.apply} · scanned {scanned} · orphans {removed}\n\n"
        f"Root: `{root}`\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "apply": args.apply,
                "root": str(root),
                "scanned": scanned,
                "orphans": removed,
                "samples": samples[:8],
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
