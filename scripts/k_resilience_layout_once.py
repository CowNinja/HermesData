#!/usr/bin/env python3
"""K: resilience layout once - dirs, index, quarantine mega fossils.

Owns K:/Hermes-Resilience structure. Safe defaults:
  - Move hermes-full-*.zip > 10GB into Quarantine/fossils/ (same-volume rename)
  - Never delete fossils unless --delete-fossils (Jeff explicit)
  - Write K map + free space receipt

Usage:
  python D:/HermesData/scripts/k_resilience_layout_once.py
  python D:/HermesData/scripts/k_resilience_layout_once.py --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

K_ROOT = Path(r"K:\Hermes-Resilience")
HERMES = Path(r"D:\HermesData")
STATE = HERMES / "state" / "k_resilience_layout_last.json"

DIRS = [
    "backups/hermes/critical",
    "backups/hermes/dated",
    "mirrors/HermesData-Current",
    "mirrors/PhronesisVault-Critical",
    "mirrors/Personal-Digital-Silo-Signal",
    "manifests",
    "logs",
    "restore",
    "scripts",
    "tests",
    "Quarantine/fossils",
    "Quarantine/scratch",
]

FOSSIL_GLOB = "hermes-full-*.zip"
FOSSIL_MIN_BYTES = 10 * 1024 * 1024 * 1024  # 10GB


def log(m: str) -> None:
    print(m, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--delete-fossils", action="store_true",
                    help="IRREVERSIBLE delete quarantined fossils (default: move only)")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    errors: List[str] = []
    notes: List[str] = []

    if not Path("K:/").exists():
        err = {"ts": ts, "ok": False, "errors": ["K: missing"]}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(err, indent=2), encoding="utf-8")
        return 2

    K_ROOT.mkdir(parents=True, exist_ok=True)
    for d in DIRS:
        (K_ROOT / d).mkdir(parents=True, exist_ok=True)
        notes.append(f"dir_ok:{d}")

    # Quarantine mega full zips (same volume = fast rename)
    src_dir = K_ROOT / "backups" / "hermes"
    q_dir = K_ROOT / "Quarantine" / "fossils"
    moved: List[Dict[str, Any]] = []
    if src_dir.is_dir():
        for z in src_dir.glob(FOSSIL_GLOB):
            try:
                sz = z.stat().st_size
            except OSError as e:
                errors.append(str(e))
                continue
            if sz < FOSSIL_MIN_BYTES:
                continue
            dest = q_dir / z.name
            if dest.exists():
                notes.append(f"already_quarantined:{z.name}")
                continue
            try:
                z.rename(dest)
                moved.append({"name": z.name, "bytes": sz, "dest": str(dest)})
                log(f"QUARANTINE {z.name} -> {dest} ({sz/1e9:.1f}GB)")
            except OSError as e:
                # cross-link fallback
                try:
                    shutil.move(str(z), str(dest))
                    moved.append({"name": z.name, "bytes": sz, "dest": str(dest), "via": "shutil"})
                except OSError as e2:
                    errors.append(f"quarantine {z.name}: {e2}")

    if args.delete_fossils:
        for z in q_dir.glob(FOSSIL_GLOB):
            try:
                sz = z.stat().st_size
                z.unlink()
                notes.append(f"DELETED_FOSSIL:{z.name}:{sz}")
                log(f"DELETED fossil {z.name}")
            except OSError as e:
                errors.append(f"delete {z.name}: {e}")

    # Free space
    usage = {}
    try:
        t, u, f = shutil.disk_usage("K:/")
        usage = {"total_tb": round(t / 1e12, 3), "free_tb": round(f / 1e12, 3), "used_pct": round(u / t * 100, 1)}
    except Exception as e:
        errors.append(f"disk_usage: {e}")

    # Living map
    map_path = K_ROOT / "K-RESILIENCE-MAP.md"
    map_path.write_text(
        f"""# K: Hermes-Resilience map (Hermes-owned)

Updated: {ts}

Jeff never manages this volume; Hermes owns all 5TB policy here.

## Layout

| Path | Role |
|------|------|
| mirrors/HermesData-Current | 4h selective D: scripts/config/cron/skills |
| mirrors/PhronesisVault-Critical | 4h vault Operations (no logs dumps) |
| mirrors/Personal-Digital-Silo-Signal | allowlisted silo indexes/proofs |
| backups/hermes/critical | small critical-state zips (not full tree) |
| backups/hermes/dated | optional dated packs |
| Quarantine/fossils | mega accidental full zips (not active restore) |
| manifests/latest-backup.json | health-alarm age probe |
| restore/ | one-shot restore notes |

## Cadence (target)

- K slices: every **4h** via backup-resilience.py
- GitHub HermesData: every **4h** if dirty
- GitHub vault `github-cns-mirror`: **1-2x/day** (change-detect)
- Critical zip: every **4h**
- Silo signal mirror: every **4h** (budgeted)

## Free space now

{json.dumps(usage, indent=2)}

## Fossils moved this run

{json.dumps(moved, indent=2)}
""",
        encoding="utf-8",
    )

    # restore stub if missing
    restore = K_ROOT / "restore" / "RESTORE-FROM-K.md"
    if not restore.exists():
        restore.write_text(
            """# Restore from K: (catastrophe)

1. New PC + attach K: + install Python/git
2. Copy `mirrors/HermesData-Current/scripts` -> work dir
3. Copy `backups/hermes/critical/critical-*.zip` latest and expand
4. `git clone` CowNinja/HermesData + PhronesisVault branch `github-cns-mirror`
5. Run `python scripts/backup_health_alarm.py --json`
6. Silo signal: `mirrors/Personal-Digital-Silo-Signal`

Do **not** restore Quarantine/fossils unless explicitly needed.
""",
            encoding="utf-8",
        )

    ok = len(errors) == 0
    payload = {
        "ts": ts,
        "ok": ok,
        "usage": usage,
        "moved_fossils": moved,
        "errors": errors,
        "notes": notes[:40],
        "map": str(map_path),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # also drop manifest crumb
    try:
        (K_ROOT / "manifests" / "layout-last.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError:
        pass

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        log(f"DONE ok={ok} free_tb={usage.get('free_tb')} moved={len(moved)} errors={len(errors)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
