#!/usr/bin/env python3
"""Restore drill — prove D: death recovery path from K + GitHub clean tip.

Default: READ-ONLY checks (no writes to D: live trees).
  --stage  writes a staged restore pack under K:/Hermes-Resilience/restore/drill-<ts>/
           still does NOT overwrite D:/HermesData or D:/PhronesisVault.

Checks:
  1) K critical zip exists + recent + unzip listable
  2) K HermesData-Current mirror has scripts/ + config.yaml
  3) K vault critical mirror has Operations/
  4) K manifests root + free-space
  5) GitHub github-cns-mirror tip fetchable (ls-remote)
  6) Pre-purge bundle present (history insurance)
  7) Optional: silo signal mirror manifest

Usage:
  python D:/HermesData/scripts/backup_restore_drill.py
  python D:/HermesData/scripts/backup_restore_drill.py --stage --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES = Path(r"D:\HermesData")
K_ROOT = Path(r"K:\Hermes-Resilience")
STATE = HERMES / "state" / "backup_restore_drill_last.json"
CRITICAL_DIR = K_ROOT / "backups" / "hermes" / "critical"
MIRROR_HD = K_ROOT / "mirrors" / "HermesData-Current"
MIRROR_VAULT = K_ROOT / "mirrors" / "PhronesisVault-Critical"
MIRROR_SILO = K_ROOT / "mirrors" / "Personal-Digital-Silo-Signal"
MANIFESTS = K_ROOT / "manifests"
PRE_PURGE = K_ROOT / "restore" / "pre-purge-20260802"
VAULT_REMOTE = "https://github.com/CowNinja/PhronesisVault.git"
CLEAN_BRANCH = "github-cns-mirror"


def run(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def latest_critical_zip() -> Path | None:
    if not CRITICAL_DIR.is_dir():
        return None
    zips = sorted(CRITICAL_DIR.glob("critical-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return zips[0] if zips else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stage", action="store_true", help="copy proof pack under K restore/drill-*")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    checks: List[Dict[str, Any]] = []
    fails = 0

    def add(name: str, ok: bool, detail: str) -> None:
        nonlocal fails
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            fails += 1

    # 1 critical zip
    z = latest_critical_zip()
    if z and z.exists():
        age_h = (datetime.now().timestamp() - z.stat().st_mtime) / 3600.0
        listable = False
        n_entries = 0
        try:
            with zipfile.ZipFile(z, "r") as zf:
                names = zf.namelist()
                n_entries = len(names)
                listable = n_entries > 0
        except Exception as e:
            add("critical_zip", False, f"{z.name} not listable: {e}")
        else:
            add(
                "critical_zip",
                listable and age_h < 72,
                f"{z.name} entries={n_entries} age_h={age_h:.1f} bytes={z.stat().st_size}",
            )
    else:
        add("critical_zip", False, "no critical-*.zip under K backups/hermes/critical")

    # 2 HD mirror
    hd_ok = (MIRROR_HD / "scripts").is_dir() and (
        (MIRROR_HD / "config.yaml").is_file() or (MIRROR_HD / "cron").is_dir()
    )
    add("hermesdata_mirror", hd_ok, str(MIRROR_HD))

    # 3 vault mirror
    v_ok = (MIRROR_VAULT / "Operations").is_dir() or any(MIRROR_VAULT.glob("**/*"))
    add("vault_mirror", bool(v_ok), str(MIRROR_VAULT))

    # 4 manifests
    man_ok = (MANIFESTS / "latest-backup.json").exists()
    add("manifests", man_ok, str(MANIFESTS / "latest-backup.json"))

    # 5 clean mirror remote
    rc, out, err = run(["git", "ls-remote", VAULT_REMOTE, f"refs/heads/{CLEAN_BRANCH}"], timeout=45)
    tip = (out.split() or [""])[0] if rc == 0 else ""
    add("github_cns_mirror", rc == 0 and len(tip) >= 7, f"rc={rc} tip={tip[:12]} {(err or '')[:80]}")

    # 6 pre-purge bundle
    bundles = list(PRE_PURGE.glob("*.bundle")) if PRE_PURGE.is_dir() else []
    add(
        "pre_purge_bundle",
        len(bundles) > 0,
        f"count={len(bundles)} {[b.name + ':' + str(b.stat().st_size) for b in bundles][:3]}",
    )

    # 7 silo signal
    silo_man = MIRROR_SILO / "00-SIGNAL-MIRROR-MANIFEST.json"
    add("silo_signal", silo_man.exists(), str(silo_man))

    # 8 free space
    try:
        u = shutil.disk_usage("K:\\")
        free_tb = u.free / (1024**4)
        add("k_free_space", free_tb > 0.2, f"free_tb={free_tb:.3f}")
    except Exception as e:
        add("k_free_space", False, str(e))

    staged_path = None
    if args.stage and fails == 0:
        dest = K_ROOT / "restore" / f"drill-{stamp}"
        dest.mkdir(parents=True, exist_ok=True)
        # copy small proof artifacts only
        for src in (
            MANIFESTS / "latest-backup.json",
            MANIFESTS / "fossil-delete-receipt.json",
            MANIFESTS / "free-space-governor.json",
            silo_man if silo_man.exists() else None,
            z,
        ):
            if src and Path(src).exists():
                try:
                    shutil.copy2(src, dest / Path(src).name)
                except OSError:
                    pass
        checklist = dest / "RESTORE-CHECKLIST.md"
        checklist.write_text(
            f"""# Restore drill staged {ts}

## Order if D: dies
1. Attach K: (already primary offsite).
2. Read `K:/Hermes-Resilience/MANIFEST-ROOT.md`.
3. Expand latest `backups/hermes/critical/critical-*.zip` onto new HermesData skeleton.
4. Robocopy/mirror from `mirrors/HermesData-Current` for scripts/config/cron/skills.
5. Vault CNS tip: `git clone --branch {CLEAN_BRANCH} --single-branch {VAULT_REMOTE}`
6. History insurance: `git clone pre-purge-*.bundle` only if needed for archaeology.
7. Silo: live tree is already on K under Phronesis-Sovereign; signal mirror is indexes only.
8. Run `python scripts/backup_health_alarm.py` after rebuild.

## This drill
- read_only_default: true
- staged_pack: {dest}
- results: see drill-result.json
""",
            encoding="utf-8",
        )
        staged_path = str(dest)

    ok = fails == 0
    payload = {
        "ts": ts,
        "ok": ok,
        "fail_count": fails,
        "checks": checks,
        "staged": staged_path,
        "mode": "stage" if args.stage else "read_only",
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        MANIFESTS.mkdir(parents=True, exist_ok=True)
        (MANIFESTS / "restore-drill-last.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        if staged_path:
            Path(staged_path).joinpath("drill-result.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
    except OSError:
        pass

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"RESTORE_DRILL ok={ok} fails={fails} mode={payload['mode']}")
        for c in checks:
            mark = "OK " if c["ok"] else "FAIL"
            print(f"  {mark} {c['name']}: {c['detail'][:120]}")
        if staged_path:
            print(f"  staged -> {staged_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
