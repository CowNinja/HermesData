#!/usr/bin/env python3
"""Content-aware domain suggestion for Inbox files using peek + domain_route.

Does NOT move by default; --apply copies to new domain shelf under from-g-drive
(re-home style) and updates tags in .context.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
from domain_route import domain_for  # noqa: E402
from file_context_enrich import enrich_one, peek_text  # noqa: E402

INBOX = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not INBOX.is_dir():
        print({"error": "no_inbox"})
        return 2

    files = [p for p in INBOX.rglob("*") if p.is_file() and not any(
        p.name.endswith(s) for s in (
            ".meta.json", ".train.md", ".context.json", ".context.train.md",
            ".ocr.md", ".needs_ocr", ".extract.json",
        )
    )]
    files = files[: args.limit * 3]
    proposed = []
    moved = 0
    for p in files:
        if len(proposed) >= args.limit:
            break
        peek = peek_text(p, 2500)
        blob_path = str(p)
        guess = domain_for(p.name, f"{blob_path} {peek[:800]}")
        if guess.endswith("_Inbox") or guess == "Core-Personal/_Inbox":
            continue
        proposed.append({"file": p.name, "from": "Core-Personal/_Inbox", "to": guess})
        if not args.apply:
            continue
        # re-home copy
        dest_dir = SILO / guess / "from-g-drive"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        if dest.exists():
            dest = dest_dir / f"{p.stem}__reroute{p.suffix}"
        try:
            shutil.copy2(p, dest)
            # copy meta if any
            meta = Path(str(p) + ".meta.json")
            if meta.is_file():
                shutil.copy2(meta, Path(str(dest) + ".meta.json"))
            enrich_one(dest, write=True)
            moved += 1
        except Exception as e:
            proposed[-1]["error"] = str(e)[:120]

    print(json.dumps({"proposed": len(proposed), "moved": moved, "sample": proposed[:15]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
