#!/usr/bin/env python3
"""Build a small Phronesis recovery pack and sync to cloud destination if present.

Targets (first hit wins):
  - G:/My Drive/Phronesis-Recovery
  - G:/MyDrive/Phronesis-Recovery
  - <user>/Google Drive/Phronesis-Recovery
  - <user>/OneDrive/Phronesis-Recovery  (interim)

Never copies .env, auth.json, state.db, large media.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_text = None  # type: ignore

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
K_RES = Path(r"K:\Hermes-Resilience")
STAGING = HERMES / "Backups" / "Phronesis-Recovery-Staging"
RECEIPT = VAULT / "Operations" / "logs" / "cloud-recovery-pack-sync-latest.md"

# Curated relative copies: (src, dest_under_pack)
PACK_FILES: list[tuple[Path, str]] = [
    (VAULT / "Operations" / "Catastrophe-Restore-and-Backup-Hardening-2026-07-10.md", "Operations/Catastrophe-Restore-and-Backup-Hardening-2026-07-10.md"),
    (VAULT / "Operations" / "K-Silo-Holistic-Foundation-2026-07-10.md", "Operations/K-Silo-Holistic-Foundation-2026-07-10.md"),
    (VAULT / "Operations" / "K-Life-Domain-Taxonomy-CANONICAL-2026-07-10.md", "Operations/K-Life-Domain-Taxonomy-CANONICAL-2026-07-10.md"),
    (VAULT / "Operations" / "K-Silo-No-Stone-Unturned-Patterns-Bookmark-2026-07-10.md", "Operations/K-Silo-No-Stone-Unturned-Patterns-Bookmark-2026-07-10.md"),
    (VAULT / "Operations" / "Master-Orchestrator-Path-2026-07-10.md", "Operations/Master-Orchestrator-Path-2026-07-10.md"),
    (VAULT / "Operations" / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md", "Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md"),
    (VAULT / "Housekeeping.md", "Housekeeping.md"),
    (HERMES / "scripts" / "backup-resilience.py", "scripts-critical/backup-resilience.py"),
    (HERMES / "scripts" / "backup-resilience.sh", "scripts-critical/backup-resilience.sh"),
    (HERMES / "scripts" / "cloud_recovery_pack_sync.py", "scripts-critical/cloud_recovery_pack_sync.py"),
    (HERMES / "scripts" / "stack_healing_once.py", "scripts-critical/stack_healing_once.py"),
    (HERMES / "memories" / "MEMORY.md", "memories/MEMORY.md"),
    (HERMES / "memories" / "USER.md", "memories/USER.md"),
    (K_RES / "phronesis-resilience.md", "phronesis-resilience.md"),
    (K_RES / "restore" / "restore.ps1", "restore/restore.ps1"),
    (K_RES / "restore" / "restore.sh", "restore/restore.sh"),
    (K_RES / "manifests" / "latest-backup.json", "manifests/latest-backup.json"),
]


def cloud_destinations() -> list[Path]:
    """Prefer Google Drive (Drive for Desktop mirror), then OneDrive.

    After off-C move, also check D:\\CloudSync\\* roots (see Move playbook).
    """
    home = Path(os.environ.get("USERPROFILE", r"C:\Users\CowNi"))
    return [
        # Post-move targets (D: off C-space)
        Path(r"D:\CloudSync\Google-My-Drive\Phronesis-Recovery"),
        Path(r"D:\CloudSync\OneDrive\Phronesis-Recovery"),
        # Google Drive for Desktop — current mirror root on this host
        home / "My Drive" / "Phronesis-Recovery",
        Path(r"G:\My Drive\Phronesis-Recovery"),
        Path(r"G:\MyDrive\Phronesis-Recovery"),
        home / "Google Drive" / "Phronesis-Recovery",
        home / "GoogleDrive" / "Phronesis-Recovery",
        # OneDrive (current C: location until relocated)
        home / "OneDrive" / "Phronesis-Recovery",
    ]


def build_pack() -> list[str]:
    if STAGING.exists():
        shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    copied = []
    for src, rel in PACK_FILES:
        if not src.exists():
            copied.append(f"MISS {rel}")
            continue
        dest = STAGING / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(f"OK {rel}")
    readme = STAGING / "README-RESTORE.md"
    readme.write_text(
        f"""# Phronesis Recovery Pack

Built: {TS}

## Contains
Critical Operations CNS, backup scripts, memories (MEMORY/USER), K restore scripts, resilience notes.

## Does NOT contain
Secrets (.env, auth.json), full state.db, Comfy media, full K life silo bulk.

## Restore sketch
1. Clone GitHub PhronesisVault + HermesData if available
2. Plug K: and run Hermes-Resilience/restore/restore.ps1
3. Copy memories/ + Operations/ from this pack if needed
4. Re-auth secrets from password manager
5. hermes doctor / start gateway

See Operations/Catastrophe-Restore-and-Backup-Hardening-2026-07-10.md
""",
        encoding="utf-8",
    )
    return copied


def sync_to(dest: Path) -> tuple[bool, str]:
    dest.mkdir(parents=True, exist_ok=True)
    # robocopy via powershell for reliability
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        f"robocopy '{STAGING}' '{dest}' /E /R:1 /W:2 /NFL /NDL /NJH /NJS /NP; if ($LASTEXITCODE -ge 8) {{ exit $LASTEXITCODE }} else {{ exit 0 }}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        return ok, f"rc={r.returncode} {(r.stderr or r.stdout or '')[:200]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    copied = build_pack()
    chosen = None
    sync_msg = "no cloud destination found"
    for d in cloud_destinations():
        # parent must exist (cloud root mounted)
        if d.parent.exists():
            ok, msg = sync_to(d)
            sync_msg = f"{d}: {msg}"
            if ok:
                chosen = d
                break
            sync_msg = f"fail {d}: {msg}"

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    receipt_body = "\n".join(
        [
            f"# Cloud recovery pack sync — {TS}",
            "",
            f"**Staging:** `{STAGING}`",
            f"**Cloud dest:** `{chosen or 'NONE — pack built locally only'}`",
            f"**Sync:** {sync_msg}",
            "",
            "## Files",
            *[f"- {c}" for c in copied],
            "",
            "[[Operations/Catastrophe-Restore-and-Backup-Hardening-2026-07-10]]",
            "",
        ]
    )
    if atomic_write_text is not None:
        atomic_write_text(RECEIPT, receipt_body, min_bytes=20)
    else:
        RECEIPT.write_text(
            receipt_body if receipt_body.endswith("\n") else receipt_body + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "staging": str(STAGING),
                "cloud": str(chosen) if chosen else None,
                "sync": sync_msg,
                "files": len(copied),
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0 if chosen else 2  # 2 = pack built, cloud missing


if __name__ == "__main__":
    raise SystemExit(main())
