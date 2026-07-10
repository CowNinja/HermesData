#!/usr/bin/env python3
"""Read-only K: silo tranche audit -- no RP content, zero VRAM."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from garden_wall import audit_isolation, is_rp_or_explicit_path

SILO_ROOT = Path(r"K:\Phronesis-Sovereign")
SILO_INDEX = SILO_ROOT / "00-MASTER-K-SOVEREIGN-INDEX.md"
STAGING = Path(r"D:\HermesData\data\silo_ingest")
VAULT_MIRROR = Path(r"D:\PhronesisVault")
DK_HARMONY = VAULT_MIRROR / "D-K-Harmony.md"
OUTPUT = Path(r"D:\PhronesisVault\Operations\logs\wisdomkeeper-silo-audit.json")


def _count_tranches(root: Path) -> Dict[str, Any]:
    if not root.is_dir():
        return {"ok": False, "error": "k_silo_not_mounted", "tranche_count": 0, "tranches": []}

    tranches: List[Dict[str, Any]] = []
    scan_roots = [
        root / "test-ingest",
        root / "Personal-Digital-Silo",
    ]
    for base in scan_roots:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if is_rp_or_explicit_path(child):
                continue
            if child.is_dir():
                manifest = list(child.glob("**/enrichment_manifest.json"))
                tranches.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "manifests": len(manifest),
                    }
                )
    return {
        "ok": True,
        "tranche_count": len(tranches),
        "tranches": tranches[:50],
    }


def run_audit() -> Dict[str, Any]:
    wall = audit_isolation()
    tranches = _count_tranches(SILO_ROOT)
    staging_dirs = 0
    if STAGING.is_dir():
        staging_dirs = sum(1 for p in STAGING.iterdir() if p.is_dir())

    return {
        "ok": tranches.get("ok", False) and wall.get("isolated", False),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "silo_root": str(SILO_ROOT),
        "silo_index_exists": SILO_INDEX.is_file(),
        "dk_harmony_exists": DK_HARMONY.is_file(),
        "staging_dir_count": staging_dirs,
        "tranches": tranches,
        "garden_wall": wall,
        "note": "RP sandbox excluded; recall layer pending",
    }


def main() -> int:
    result = run_audit()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())