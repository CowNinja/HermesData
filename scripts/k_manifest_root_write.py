#!/usr/bin/env python3
"""Write single recovery index: K:/Hermes-Resilience/MANIFEST-ROOT.md + JSON."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

HERMES = Path(r"D:\HermesData")
K_ROOT = Path(r"K:\Hermes-Resilience")
OUT_MD = K_ROOT / "MANIFEST-ROOT.md"
OUT_JSON = K_ROOT / "manifests" / "MANIFEST-ROOT.json"
STATE = HERMES / "state" / "k_manifest_root_last.json"


def age_h(p: Path) -> Optional[float]:
    if not p.exists():
        return None
    return round((datetime.now().timestamp() - p.stat().st_mtime) / 3600.0, 2)


def load(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    u = shutil.disk_usage("K:\\")
    usage = {
        "total_tb": round(u.total / 1024**4, 3),
        "free_tb": round(u.free / 1024**4, 3),
        "used_pct": round(100 * (u.total - u.free) / u.total, 2),
    }

    crit = sorted(
        (K_ROOT / "backups" / "hermes" / "critical").glob("critical-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    crit0 = crit[0] if crit else None
    bundles = list((K_ROOT / "restore" / "pre-purge-20260802").glob("*.bundle"))

    layers = {
        "hermesdata_mirror": {
            "path": str(K_ROOT / "mirrors" / "HermesData-Current"),
            "age_h": age_h(K_ROOT / "mirrors" / "HermesData-Current"),
            "state": str(HERMES / "state" / "backup_k_mirror_last.json"),
        },
        "vault_mirror": {
            "path": str(K_ROOT / "mirrors" / "PhronesisVault-Critical"),
            "age_h": age_h(K_ROOT / "mirrors" / "PhronesisVault-Critical"),
        },
        "silo_signal": {
            "path": str(K_ROOT / "mirrors" / "Personal-Digital-Silo-Signal"),
            "age_h": age_h(
                K_ROOT / "mirrors" / "Personal-Digital-Silo-Signal" / "00-SIGNAL-MIRROR-MANIFEST.json"
            ),
            "state": str(HERMES / "state" / "backup_k_silo_life_mirror_last.json"),
        },
        "critical_zip": {
            "path": str(crit0) if crit0 else None,
            "age_h": age_h(crit0) if crit0 else None,
            "bytes": crit0.stat().st_size if crit0 else None,
        },
        "latest_backup_manifest": {
            "path": str(K_ROOT / "manifests" / "latest-backup.json"),
            "age_h": age_h(K_ROOT / "manifests" / "latest-backup.json"),
        },
        "github_cns_mirror": {
            "repo": "https://github.com/CowNinja/PhronesisVault.git",
            "branch": "github-cns-mirror",
            "state": str(HERMES / "state" / "vault_github_clean_mirror_last.json"),
            "last": load(HERMES / "state" / "vault_github_clean_mirror_last.json"),
        },
        "hermesdata_github": {
            "repo": "origin/main under D:/HermesData",
            "state": str(HERMES / "state" / "backup_resilience_last.json"),
        },
        "pre_purge_bundle": {
            "paths": [str(b) for b in bundles],
            "bytes": [b.stat().st_size for b in bundles],
        },
        "fossil_delete": load(K_ROOT / "manifests" / "fossil-delete-receipt.json"),
        "free_space_governor": load(K_ROOT / "manifests" / "free-space-governor.json"),
        "restore_drill": load(K_ROOT / "manifests" / "restore-drill-last.json"),
        "poison_guard": load(HERMES / "state" / "vault_poison_guard_last.json"),
        "silo_live_ssot": r"K:\Phronesis-Sovereign\Personal-Digital-Silo",
    }

    slo = {
        "k_mirror_max_age_h": 48,
        "critical_zip_max_age_h": 48,
        "clean_mirror_max_age_h": 36,
        "manifest_max_age_h": 48,
        "min_free_tb": 0.75,
    }

    payload = {
        "ts": ts,
        "owner": "Hermes (Jeff never manages K:)",
        "usage": usage,
        "slo": slo,
        "layers": layers,
        "recovery_order": [
            "MANIFEST-ROOT.md (this file)",
            "backups/hermes/critical/critical-*.zip",
            "mirrors/HermesData-Current",
            "mirrors/PhronesisVault-Critical",
            "git clone --branch github-cns-mirror PhronesisVault",
            "silo live on K:/Phronesis-Sovereign/Personal-Digital-Silo",
            "pre-purge bundle only for history archaeology",
        ],
    }

    md = f"""# K: Hermes-Resilience - MANIFEST ROOT

**Owner:** Hermes (5TB baby - Jeff never manages)  
**Updated:** {ts}  
**Free:** {usage['free_tb']} TB ({usage['used_pct']}% used)

## Where things live

| Layer | Path / ref | Age h |
|-------|------------|-------|
| Critical zip | `{layers['critical_zip']['path']}` | {layers['critical_zip']['age_h']} |
| HermesData mirror | `{layers['hermesdata_mirror']['path']}` | {layers['hermesdata_mirror']['age_h']} |
| Vault critical mirror | `{layers['vault_mirror']['path']}` | {layers['vault_mirror']['age_h']} |
| Silo signal mirror | `{layers['silo_signal']['path']}` | {layers['silo_signal']['age_h']} |
| Silo live SSOT | `{layers['silo_live_ssot']}` | n/a |
| latest-backup.json | `{layers['latest_backup_manifest']['path']}` | {layers['latest_backup_manifest']['age_h']} |
| GitHub CNS tip | `PhronesisVault` branch `github-cns-mirror` | see state |
| Pre-purge bundle | `{layers['pre_purge_bundle']['paths']}` | insurance |
| Fossil delete receipt | `manifests/fossil-delete-receipt.json` | done 2026-08-02 |

## SLO

- K mirror / critical zip / manifest age ** {slo['k_mirror_max_age_h']}h**
- Clean GitHub mirror ** {slo['clean_mirror_max_age_h']}h**
- Free space ** {slo['min_free_tb']} TB**

## Recovery order (D: dies)

1. Read this file on K:
2. Expand latest critical zip -> new HermesData skeleton  
3. Overlay `mirrors/HermesData-Current`  
4. `git clone --branch github-cns-mirror --single-branch https://github.com/CowNinja/PhronesisVault.git`  
5. Silo already on K live tree; signal mirror = indexes only  
6. `python scripts/backup_health_alarm.py` + `backup_restore_drill.py`

## Cadence spine

`python D:/HermesData/scripts/backup-resilience.py` every 4h (cron).

Machine JSON: `manifests/MANIFEST-ROOT.json`
"""
    K_ROOT.mkdir(parents=True, exist_ok=True)
    (K_ROOT / "manifests").mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"ts": ts, "ok": True, "path": str(OUT_MD)}, indent=2), encoding="utf-8")
    print(f"MANIFEST_ROOT ok -> {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
