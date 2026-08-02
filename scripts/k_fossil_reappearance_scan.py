#!/usr/bin/env python3
"""Scan K: for reappearing giant fossils (zip/vhd/iso/wim > threshold).

After 2026-08-02 reclaim of ~183GB hermes-full zip, guard against:
  - accidental full MIR dumps
  - hermes backup --full landing on K root
  - leftover Quarantine refill

Default: report only. --quarantine moves matches under
  K:/Hermes-Resilience/Quarantine/fossils/auto-<ts>/

Never deletes. Never touches silo live tree contents except scan metadata.

Writes:
  K:/Hermes-Resilience/manifests/fossil-scan-last.json
  D:/HermesData/state/k_fossil_scan_last.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES = Path(r"D:\HermesData")
K_ROOT = Path(r"K:\Hermes-Resilience")
STATE = HERMES / "state" / "k_fossil_scan_last.json"
MAN = K_ROOT / "manifests" / "fossil-scan-last.json"

# 5 GB default - critical zips are KB-MB; full hermes dumps are 100GB+
DEFAULT_MIN_GB = 5.0
FOSSIL_SUFFIXES = {".zip", ".7z", ".vhd", ".vhdx", ".iso", ".wim", ".rar", ".bak"}
# roots to scan (shallow-to-medium). Skip live silo bulk.
SCAN_ROOTS = [
    Path(r"K:\Hermes-Resilience"),
    Path(r"K:\Backups"),
    Path(r"K:\HermesData"),
    Path(r"K:\PhronesisVault"),
]
SKIP_DIR_NAMES = {
    "Personal-Digital-Silo",  # never treat silo media as fossil
    "System Volume Information",
    "$RECYCLE.BIN",
    "node_modules",
    ".git",
}


def log(m: str) -> None:
    print(m, flush=True)


def scan(min_bytes: int, budget_sec: float = 120.0) -> List[Dict[str, Any]]:
    t0 = time.time()
    found: List[Dict[str, Any]] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        if time.time() - t0 > budget_sec:
            break
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if time.time() - t0 > budget_sec:
                    break
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
                # depth cap under each scan root
                try:
                    depth = len(Path(dirpath).relative_to(root).parts)
                except ValueError:
                    depth = 0
                if depth > 4:
                    dirnames.clear()
                    continue
                for fn in filenames:
                    suf = Path(fn).suffix.lower()
                    if suf not in FOSSIL_SUFFIXES:
                        continue
                    p = Path(dirpath) / fn
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        continue
                    if sz >= min_bytes:
                        found.append(
                            {
                                "path": str(p),
                                "bytes": sz,
                                "gb": round(sz / (1024**3), 3),
                                "suffix": suf,
                            }
                        )
        except OSError as e:
            log(f"WARN walk {root}: {e}")
    found.sort(key=lambda x: x["bytes"], reverse=True)
    return found


def quarantine(items: List[Dict[str, Any]], stamp: str) -> List[Dict[str, Any]]:
    dest_root = K_ROOT / "Quarantine" / "fossils" / f"auto-{stamp}"
    dest_root.mkdir(parents=True, exist_ok=True)
    results = []
    for it in items:
        src = Path(it["path"])
        # don't move things already under Quarantine/fossils
        if "\\Quarantine\\fossils\\" in str(src) or "/Quarantine/fossils/" in str(src):
            results.append({**it, "action": "already_quarantined"})
            continue
        if not src.exists():
            results.append({**it, "action": "missing"})
            continue
        dest = dest_root / src.name
        if dest.exists():
            dest = dest_root / f"{src.stem}-{stamp}{src.suffix}"
        try:
            shutil.move(str(src), str(dest))
            results.append({**it, "action": "moved", "dest": str(dest)})
        except OSError as e:
            results.append({**it, "action": "move_failed", "error": str(e)[:160]})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-gb", type=float, default=DEFAULT_MIN_GB)
    ap.add_argument("--quarantine", action="store_true", help="move matches into Quarantine/fossils")
    ap.add_argument("--budget-sec", type=float, default=120.0)
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    min_bytes = int(args.min_gb * (1024**3))

    found = scan(min_bytes, budget_sec=args.budget_sec)
    # split: already in quarantine vs live danger
    live = [
        f
        for f in found
        if "\\Quarantine\\fossils\\" not in f["path"] and "/Quarantine/fossils/" not in f["path"]
    ]
    actions: List[Dict[str, Any]] = []
    if args.quarantine and live:
        actions = quarantine(live, stamp)

    color = "GREEN"
    if live:
        color = "YELLOW" if sum(x["gb"] for x in live) < 50 else "RED"

    payload = {
        "ts": ts,
        "ok": color != "RED",
        "color": color,
        "min_gb": args.min_gb,
        "found_total": len(found),
        "live_danger": live,
        "live_count": len(live),
        "live_gb": round(sum(x["gb"] for x in live), 3),
        "actions": actions,
        "version": 1,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        MAN.parent.mkdir(parents=True, exist_ok=True)
        MAN.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        log(
            f"FOSSIL_SCAN color={color} live={len(live)} live_gb={payload['live_gb']} "
            f"total_found={len(found)}"
        )
        for x in live[:10]:
            log(f"  LIVE {x['gb']}GB {x['path']}")
    return 0 if color != "RED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
