#!/usr/bin/env python3
"""Batch file_context_enrich on high-value shelves."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from file_context_enrich import enrich_one  # noqa: E402

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
SHELVES = [
    "Medical-Records/from-g-drive",
    "Core-Personal/Family/from-g-drive",
    "Core-Personal/Projects/from-g-drive",
    "Navy-Service/from-g-drive",
]
SKIP_SUFFIX = (
    ".meta.json",
    ".train.md",
    ".context.json",
    ".context.train.md",
    ".ocr.md",
    ".needs_ocr",
    ".extract.json",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--per-shelf", type=int, default=25)
    args = ap.parse_args()
    ok = 0
    err = 0
    samples = []
    for rel in SHELVES:
        root = SILO / rel
        if not root.is_dir():
            continue
        n = 0
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name.startswith("00-INDEX") or p.name.upper()=="DESKTOP.INI":
                continue
            if any(p.name.endswith(s) for s in SKIP_SUFFIX):
                continue
            if Path(str(p) + ".context.json").is_file():
                continue
            try:
                ctx = enrich_one(p, write=True)
                ok += 1
                n += 1
                if len(samples) < 8:
                    samples.append({"file": p.name, "tags": ctx.get("tags"), "domain": ctx.get("domain_route")})
            except Exception as e:
                err += 1
            if n >= args.per_shelf or ok >= args.limit:
                break
        if ok >= args.limit:
            break
    print(json.dumps({"enriched": ok, "errors": err, "sample": samples}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
