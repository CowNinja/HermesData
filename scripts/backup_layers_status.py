#!/usr/bin/env python3
"""Probe all backup layers; write vault receipt. Read-only."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OUT = VAULT / "Operations" / "logs" / "backup-layers-status-latest.md"
RESILIENCE_STATE = Path(r"D:\HermesData\state\backup_resilience_last.json")
K_LATEST = Path(r"K:\Hermes-Resilience\manifests\latest-backup.json")


def run_git(repo: Path, args: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"err {e}"


def git_head(repo: Path) -> str:
    return run_git(repo, ["log", "-1", "--oneline"])[:80]


def git_branch(repo: Path) -> str:
    return run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])[:60]


def origin_lag(repo: Path, branch: str) -> str:
    """Commits local branch is ahead of origin/branch (if origin ref exists)."""
    # prefer origin/<branch>; fall back to origin/HEAD
    for ref in (f"origin/{branch}", "origin/HEAD", "origin/master", "origin/main"):
        ahead = run_git(repo, ["rev-list", "--count", f"{ref}..HEAD"])
        if ahead.isdigit():
            behind = run_git(repo, ["rev-list", "--count", f"HEAD..{ref}"])
            b = behind if behind.isdigit() else "?"
            return f"vs {ref}: ahead={ahead} behind={b}"
    return "origin lag n/a"


def age_days(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        mtime = path.stat().st_mtime
        days = (datetime.now().timestamp() - mtime) / 86400.0
        return f"{days:.1f}d"
    except Exception as e:
        return f"err {e}"


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    rows: list[str] = []

    for name, path, stable in [
        ("PhronesisVault", Path(r"D:\PhronesisVault"), "master"),
        ("HermesData", Path(r"D:\HermesData"), "main"),
    ]:
        br = git_branch(path)
        head = git_head(path)
        lag = origin_lag(path, stable)
        remote = run_git(path, ["remote", "get-url", "origin"])[:60]
        rows.append(
            f"| GitHub {name} | `{remote}` HEAD=`{br}` | `{head}`  {lag} |"
        )

    k = Path(r"K:\Hermes-Resilience")
    rows.append(
        f"| K Hermes-Resilience | exists={k.is_dir()} | "
        f"restore={(k / 'restore' / 'restore.ps1').exists()} "
        f"latest_manifest_age={age_days(K_LATEST)} |"
    )
    rows.append(
        f"| K mirrors HermesData-Current | "
        f"exists={(k / 'mirrors' / 'HermesData-Current').is_dir()} | "
        f"age={age_days(k / 'mirrors' / 'HermesData-Current')} |"
    )
    silo = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
    rows.append(f"| K Personal-Digital-Silo | exists={silo.is_dir()} | git=no (bulk) |")
    mem = Path(r"D:\HermesData\memories\MEMORY.md")
    rows.append(f"| Memories MEMORY.md | exists={mem.exists()} | age={age_days(mem)} |")

    if RESILIENCE_STATE.exists():
        try:
            st = json.loads(RESILIENCE_STATE.read_text(encoding="utf-8"))
            rows.append(
                f"| Last resilience job | ok={st.get('ok')} ts={st.get('ts','')[:19]} | "
                f"errors={st.get('error_count', 0)} |"
            )
        except Exception as e:
            rows.append(f"| Last resilience job | parse_err | {e} |")
    else:
        rows.append("| Last resilience job | no state file | run backup-resilience.py |")

    home = Path.home()
    for c in [Path(r"G:\My Drive"), home / "Google Drive", home / "OneDrive"]:
        rows.append(f"| Cloud root `{c}` | exists={c.exists()} | |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(
            [
                f"# Backup layers status - {ts}",
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
