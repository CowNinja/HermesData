#!/usr/bin/env python3
"""Probe all backup layers; write vault receipt. Read-only."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OUT = VAULT / "Operations" / "logs" / "backup-layers-status-latest.md"


def git_head(repo: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--oneline"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (r.stdout or r.stderr or "").strip()[:80]
    except Exception as e:
        return f"err {e}"


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    # GitHub repos
    for name, path, branch in [
        ("PhronesisVault", Path(r"D:\PhronesisVault"), "master"),
        ("HermesData", Path(r"D:\HermesData"), "main"),
    ]:
        remote = subprocess.run(
            ["git", "-C", str(path), "remote", "-v"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        rows.append(
            f"| GitHub {name} | `{(remote.stdout or '').splitlines()[0] if remote.stdout else 'none'}` | head `{git_head(path)}` |"
        )

    k = Path(r"K:\Hermes-Resilience")
    rows.append(f"| K Hermes-Resilience | exists={k.is_dir()} | restore={(k / 'restore' / 'restore.ps1').exists()} |")
    rows.append(
        f"| K mirrors HermesData-Current | exists={(k / 'mirrors' / 'HermesData-Current').is_dir()} | |"
    )
    silo = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
    rows.append(f"| K Personal-Digital-Silo | exists={silo.is_dir()} | git=no (bulk) |")
    mem = Path(r"D:\HermesData\memories\MEMORY.md")
    rows.append(f"| Memories MEMORY.md | exists={mem.exists()} | |")
    # cloud
    home = Path.home()
    clouds = [
        Path(r"G:\My Drive"),
        home / "Google Drive",
        home / "OneDrive",
    ]
    for c in clouds:
        rows.append(f"| Cloud root `{c}` | exists={c.exists()} | |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(
            [
                f"# Backup layers status — {ts}",
                "",
                "| Layer | Detail | Note |",
                "|-------|--------|------|",
                *rows,
                "",
                "[[Operations/Catastrophe-Restore-and-Backup-Hardening-2026-07-10]]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"out": str(OUT), "rows": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
