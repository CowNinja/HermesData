#!/usr/bin/env python3
"""Local critical-state zip (replaces hanging `hermes backup --quick`).

Allowlisted small files only -> D:/HermesData/Backups/critical/ + optional K:.
Never packs .env, auth.json, sqlite, media, venvs.

Usage:
  python D:/HermesData/scripts/backup_critical_state_zip.py
  python D:/HermesData/scripts/backup_critical_state_zip.py --to-k
  python D:/HermesData/scripts/backup_critical_state_zip.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
OUT_DIR = HERMES / "Backups" / "critical"
K_DIR = Path(r"K:\Hermes-Resilience\backups\hermes\critical")
STATE = HERMES / "state" / "backup_critical_zip_last.json"
KEEP = 8  # retain last N zips on D:

# (src_root, relative patterns - files only)
INCLUDE: List[Tuple[Path, Tuple[str, ...]]] = [
    (HERMES, (
        "config.yaml",
        "cron/jobs.json",
        "live_cron_hook.py",
        "memories/MEMORY.md",
        "memories/USER.md",
        "SOUL.md",
        "AGENTS.md",
    )),
    (HERMES / "state", (
        "backup_resilience_last.json",
        "backup_k_mirror_last.json",
        "backup_health_last.json",
        "backup_critical_zip_last.json",
        "vault_github_clean_mirror_last.json",
        "silo_continuous_state.json",
    )),
    (VAULT / "Operations", (
        "Backup-Architecture-Cook-2026-08-01.md",
        "Backup-Architecture-Audit-2026-08-01.md",
        "Vault-GitHub-History-Purge-Runbook-2026-08-01.md",
        "Catastrophe-Restore-and-Backup-Hardening-2026-07-10.md",
        "Housekeeping.md",
    )),
]

# whole small trees (depth-capped by max files)
TREE_CAPS = [
    (HERMES / "scripts" / "ops", 80),
    (HERMES / "config", 120),
]

SKIP_SUFFIX = {".sqlite", ".sqlite-wal", ".sqlite-shm", ".env", ".pem", ".key", ".zip", ".7z"}
SKIP_NAMES = {".env", "auth.json", "auth.lock"}


def log(m: str) -> None:
    print(m, flush=True)


def ok_file(p: Path) -> bool:
    if not p.is_file():
        return False
    if p.name in SKIP_NAMES:
        return False
    if p.suffix.lower() in SKIP_SUFFIX:
        return False
    try:
        if p.stat().st_size > 25 * 1024 * 1024:
            return False
    except OSError:
        return False
    return True


def collect() -> List[Tuple[Path, str]]:
    """Return list of (abs_path, arcname)."""
    items: List[Tuple[Path, str]] = []
    seen = set()

    def add(abs_p: Path, arc: str) -> None:
        key = str(abs_p).lower()
        if key in seen or not ok_file(abs_p):
            return
        seen.add(key)
        items.append((abs_p, arc.replace("\\", "/")))

    for root, rels in INCLUDE:
        for rel in rels:
            p = root / rel if root.name != Path(rel).parts[0] else HERMES / rel
            # root already includes path base
            p = (root / rel) if not rel.startswith(str(root)) else Path(rel)
            p = root / rel
            arc = f"{root.name}/{rel}" if root != HERMES else rel
            if root == VAULT / "Operations":
                arc = f"PhronesisVault/Operations/{Path(rel).name}"
            elif root == HERMES / "state":
                arc = f"state/{Path(rel).name}"
            elif root == HERMES:
                arc = rel
            add(p, arc)

    for tree, cap in TREE_CAPS:
        if not tree.is_dir():
            continue
        n = 0
        for p in sorted(tree.rglob("*")):
            if n >= cap:
                break
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(HERMES)
            except ValueError:
                continue
            add(p, str(rel).replace("\\", "/"))
            n += 1

    # always include top backup scripts by name
    for name in (
        "backup-resilience.py",
        "backup_k_mirror_once.py",
        "backup_health_alarm.py",
        "backup_critical_state_zip.py",
        "backup_k_silo_life_mirror_once.py",
        "vault_github_clean_mirror_push.py",
        "cloud_recovery_pack_sync.py",
        "k_resilience_layout_once.py",
    ):
        p = HERMES / "scripts" / name
        add(p, f"scripts/{name}")

    return items


def prune(dir_path: Path, keep: int) -> None:
    if not dir_path.is_dir():
        return
    zips = sorted(dir_path.glob("critical-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in zips[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to-k", action="store_true", default=True)
    ap.add_argument("--no-k", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    to_k = args.to_k and not args.no_k

    ts = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"critical-{stamp}.zip"

    files = collect()
    if not files:
        err = {"ts": ts, "ok": False, "error": "no_files"}
        STATE.write_text(json.dumps(err, indent=2), encoding="utf-8")
        return 1

    h = hashlib.sha256()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for abs_p, arc in files:
            try:
                data = abs_p.read_bytes()
            except OSError:
                continue
            zf.writestr(arc, data)
            h.update(arc.encode("utf-8", "replace"))
            h.update(data[:4096])

    k_path = None
    if to_k:
        try:
            K_DIR.mkdir(parents=True, exist_ok=True)
            k_path = K_DIR / out.name
            shutil.copy2(out, k_path)
            prune(K_DIR, KEEP)
        except Exception as e:
            k_path = f"ERR:{e}"

    prune(OUT_DIR, KEEP)
    payload = {
        "ts": ts,
        "ok": True,
        "path": str(out),
        "bytes": out.stat().st_size,
        "files": len(files),
        "sha256_prefix": h.hexdigest()[:16],
        "k_path": str(k_path) if k_path else None,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        log(f"OK critical zip {out} bytes={payload['bytes']} files={payload['files']} k={k_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
