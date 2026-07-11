#!/usr/bin/env python3
"""Placeholder lexicon: when in doubt, annotate names/titles for later fill-in."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ENTITY = Path(r"D:\HermesData\config\entity_context.json")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load() -> dict:
    return json.loads(ENTITY.read_text(encoding="utf-8"))


def save(d: dict) -> None:
    d["updated"] = utc()
    ENTITY.write_text(json.dumps(d, indent=2), encoding="utf-8")


def ensure_placeholder(
    name: str,
    kind: str = "person",
    domain: str = "Core-Personal/_Inbox",
    context: str = "",
) -> str:
    """Add placeholder if missing. Never overwrites confirmed Jeff entries."""
    d = load()
    key = name.strip().lower()
    if len(key) < 3:
        return "skip_short"
    bucket = "people" if kind == "person" else "orgs"
    for row in d.get(bucket) or []:
        names = [n.lower() for n in (row.get("names") or [])]
        if key in names or any(key == n for n in names):
            return "exists"
        # don't touch confirmed sources
        if row.get("source", "").startswith("jeff") and key in " ".join(names):
            return "exists_jeff"
    row = {
        "names": [key],
        "role": "placeholder",
        "domain": domain,
        "notes": f"PLACEHOLDER — annotate until more data. ctx: {context[:200]}",
        "status": "placeholder",
        "source": "auto_placeholder",
        "updated": utc(),
    }
    d.setdefault(bucket, []).append(row)
    save(d)
    return "added"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--kind", default="person", choices=["person", "org"])
    ap.add_argument("--domain", default="Core-Personal/_Inbox")
    ap.add_argument("--context", default="")
    args = ap.parse_args()
    print(ensure_placeholder(args.name, args.kind, args.domain, args.context))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
