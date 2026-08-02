#!/usr/bin/env python3
"""K: free-space governor - Hermes owns the 5TB baby.

Budgets (soft targets, not hard partitions):
  silo live tree     keep working headroom
  Hermes-Resilience  mirrors + critical zips + manifests
  Quarantine         fossils/scratch - alarm if refilled

Writes:
  K:/Hermes-Resilience/manifests/free-space-governor.json
  D:/HermesData/state/k_free_space_governor_last.json

Exit: 0 ok/warn, 1 hard issues (K missing / critically full)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES = Path(r"D:\HermesData")
K_ROOT = Path(r"K:\Hermes-Resilience")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
STATE = HERMES / "state" / "k_free_space_governor_last.json"
MAN = K_ROOT / "manifests" / "free-space-governor.json"

# thresholds
WARN_FREE_TB = 0.75
CRIT_FREE_TB = 0.35
WARN_USED_PCT = 85.0
CRIT_USED_PCT = 93.0
FOSSIL_WARN_GB = 20.0


def du_bytes(path: Path, depth_files_cap: int = 200_000) -> int:
    total = 0
    n = 0
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
                    n += 1
                    if n >= depth_files_cap:
                        break
            except OSError:
                continue
    except OSError:
        return total
    return total


def disk_usage(root: str = "K:\\") -> Dict[str, float]:
    u = shutil.disk_usage(root)
    tb = 1024**4
    return {
        "total_tb": round(u.total / tb, 3),
        "free_tb": round(u.free / tb, 3),
        "used_tb": round((u.total - u.free) / tb, 3),
        "used_pct": round(100.0 * (u.total - u.free) / u.total, 2),
        "free_bytes": u.free,
        "total_bytes": u.total,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--deep", action="store_true", help="du major trees (slower)")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    issues: List[str] = []
    warns: List[str] = []

    if not Path("K:/").exists():
        payload = {"ts": ts, "ok": False, "color": "RED", "errors": ["K: missing"]}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2) if args.json else "RED K missing")
        return 1

    usage = disk_usage("K:\\")
    trees: Dict[str, Any] = {}
    if args.deep:
        for label, p in (
            ("hermes_resilience", K_ROOT),
            ("silo", SILO),
            ("quarantine_fossils", K_ROOT / "Quarantine" / "fossils"),
            ("mirrors", K_ROOT / "mirrors"),
            ("backups_critical", K_ROOT / "backups" / "hermes" / "critical"),
        ):
            b = du_bytes(p)
            trees[label] = {"path": str(p), "bytes": b, "gb": round(b / (1024**3), 2)}
    else:
        # cheap: only quarantine + critical dir sizes (shallow-ish)
        for label, p in (
            ("quarantine_fossils", K_ROOT / "Quarantine" / "fossils"),
            ("backups_critical", K_ROOT / "backups" / "hermes" / "critical"),
            ("manifests", K_ROOT / "manifests"),
        ):
            b = du_bytes(p, depth_files_cap=50_000)
            trees[label] = {"path": str(p), "bytes": b, "gb": round(b / (1024**3), 2)}

    fossil_gb = float((trees.get("quarantine_fossils") or {}).get("gb") or 0)
    if fossil_gb >= FOSSIL_WARN_GB:
        warns.append(f"quarantine fossils {fossil_gb:.1f}GB >= {FOSSIL_WARN_GB}GB")

    free_tb = usage["free_tb"]
    used_pct = usage["used_pct"]
    color = "GREEN"
    if free_tb <= CRIT_FREE_TB or used_pct >= CRIT_USED_PCT:
        color = "RED"
        issues.append(f"K critically full free_tb={free_tb} used_pct={used_pct}")
    elif free_tb <= WARN_FREE_TB or used_pct >= WARN_USED_PCT or warns:
        color = "YELLOW"
        if free_tb <= WARN_FREE_TB or used_pct >= WARN_USED_PCT:
            warns.append(f"K headroom low free_tb={free_tb} used_pct={used_pct}")

    budget = {
        "policy": "Hermes-owned 5TB; Jeff never manages",
        "soft_targets": {
            "min_free_tb_warn": WARN_FREE_TB,
            "min_free_tb_crit": CRIT_FREE_TB,
            "max_used_pct_warn": WARN_USED_PCT,
            "max_used_pct_crit": CRIT_USED_PCT,
            "fossil_warn_gb": FOSSIL_WARN_GB,
            "critical_zip_not_full_tree": True,
            "silo_signal_mirror_budget_gb": 2.0,
        },
        "reclaim_order": [
            "Quarantine/fossils mega zips",
            "Quarantine/scratch",
            "backups/hermes/dated old packs",
            "never delete live silo without explicit job",
        ],
    }

    payload = {
        "ts": ts,
        "ok": len(issues) == 0,
        "color": color,
        "usage": usage,
        "trees": trees,
        "issues": issues,
        "warns": warns,
        "budget": budget,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        MAN.parent.mkdir(parents=True, exist_ok=True)
        MAN.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as e:
        payload.setdefault("errors", []).append(str(e))

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"K_GOVERNOR color={color} free_tb={free_tb} used_pct={used_pct} "
            f"issues={len(issues)} warns={len(warns)}"
        )
        for w in warns:
            print(f"  WARN: {w}")
        for i in issues:
            print(f"  ISSUE: {i}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
