#!/usr/bin/env python3
"""Pure-script ComfyUI gallery refresh for mobile UX (no LLM).

Scans recent image outputs, writes a compact JSON manifest sorted by mtime desc.
Safe while traveling: does not restart Comfy or Hermes.

Outputs:
  D:\\ComfyUI\\gallery\\manifest-latest.json
  D:\\PhronesisVault\\Operations\\logs\\comfy-gallery-refresh.jsonl
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOTS = [
    Path(r"D:\ComfyUI\output"),
    Path(r"D:\ComfyUI\gallery"),
]
OUT_JSON = Path(r"D:\ComfyUI\gallery\manifest-latest.json")
JSONL = Path(r"D:\PhronesisVault\Operations\logs\comfy-gallery-refresh.jsonl")
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_ITEMS = 200


def collect() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() not in EXTS:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                items.append(
                    {
                        "path": str(p),
                        "name": p.name,
                        "bytes": st.st_size,
                        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                        "mtime_epoch": st.st_mtime,
                    }
                )
    items.sort(key=lambda x: x["mtime_epoch"], reverse=True)
    return items[:MAX_ITEMS]


def main() -> int:
    items = collect()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": [{k: v for k, v in it.items() if k != "mtime_epoch"} for it in items],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": payload["generated_at"],
                    "count": payload["count"],
                    "out": str(OUT_JSON),
                }
            )
            + "\n"
        )
    # Non-empty stdout so cron can deliver a one-liner if desired
    print(f"gallery refresh: {payload['count']} images -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
