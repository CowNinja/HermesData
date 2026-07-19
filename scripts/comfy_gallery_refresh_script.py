#!/usr/bin/env python3
"""Pure-script ComfyUI gallery refresh for mobile UX (no LLM).

Scans recent image outputs, writes a compact JSON manifest sorted by mtime desc.
Then runs lightweight gallery.db ↔ FS reconcile (no purge, no orphan-sidecar moves).

Safe while traveling: does not restart Comfy or Hermes. Never --apply purge.

Outputs:
  D:\\ComfyUI\\gallery\\manifest-latest.json
  D:\\PhronesisVault\\Operations\\logs\\comfy-gallery-refresh.jsonl
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOTS = [
    Path(r"D:\ComfyUI\output"),
    Path(r"D:\ComfyUI\gallery"),
]
OUT_JSON = Path(r"D:\ComfyUI\gallery\manifest-latest.json")
JSONL = Path(r"D:\PhronesisVault\Operations\logs\comfy-gallery-refresh.jsonl")
PURGE = Path(r"D:\HermesData\scripts\comfy_purge_duplicate_images.py")
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_ITEMS = 200
# Reconcile is light; cap so daily cron cannot hang the gateway tick
RECONCILE_TIMEOUT_SEC = 180


def collect() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Never walk quarantine into the mobile manifest
            dirnames[:] = [d for d in dirnames if d != "_dedup_quarantine"]
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


def run_reconcile() -> dict:
    """DB↔FS + stable aliases + one FTS rebuild. No orphan-sidecar quarantine on hot path."""
    if not PURGE.is_file():
        return {"ok": False, "skip": True, "detail": f"missing {PURGE}"}
    cmd = [sys.executable, str(PURGE), "--reconcile-only"]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RECONCILE_TIMEOUT_SEC,
            cwd=str(Path(r"D:\HermesData")),
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return {
            "ok": r.returncode == 0,
            "skip": False,
            "exit": r.returncode,
            "tail": out[-800:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "skip": False, "exit": 124, "detail": "TIMEOUT"}
    except Exception as e:
        return {"ok": False, "skip": False, "exit": 1, "detail": f"{type(e).__name__}: {e}"}


def main() -> int:
    items = collect()
    recon = run_reconcile()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": [{k: v for k, v in it.items() if k != "mtime_epoch"} for it in items],
        "reconcile": {
            "ok": recon.get("ok"),
            "skip": recon.get("skip"),
            "exit": recon.get("exit"),
        },
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
                    "reconcile_ok": recon.get("ok"),
                    "reconcile_exit": recon.get("exit"),
                }
            )
            + "\n"
        )
    # Non-empty stdout so cron can deliver a one-liner if desired
    rstat = "ok" if recon.get("ok") else f"fail exit={recon.get('exit')} {recon.get('detail') or ''}".strip()
    print(f"gallery refresh: {payload['count']} images -> {OUT_JSON} | reconcile={rstat}")
    # Manifest write is the primary job; reconcile failure is soft (exit 0) so travel cron stays green
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
