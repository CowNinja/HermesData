#!/usr/bin/env python3
"""Resilience backup — runs via no_agent cron every 4h.

v3 — allowlist staging (sovereign core paths) + tracked updates + drift report.
Never commits .env or secret files.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

TS = datetime.now().strftime("%Y%m%d-%H%M%S")
ERRORS: List[str] = []

# Paths safe to stage for GitHub (no secrets, no large binaries)
ALLOWLIST: Dict[str, List[str]] = {
    r"D:\HermesData": [
        "scripts/",
        "skills/software-development/github-autobackup/",
        "hermes-workspace/src/screens/dashboard/components/",
        "hermes-workspace/src/routes/api/sovereign-stack/",
        "hermes-workspace/src/status/model-manager-strip.ts",
        "config.yaml",
        "gateway/",
        "mcps/",
        "cron/jobs.json",
        "hermes-agent/agent/chat_completion_helpers.py",
        "plugins/image_gen/comfyui_local/",
        "live_cron_hook.py",
    ],
    r"D:\PhronesisVault": [
        "Operations/",
        "scripts/",
        "MOCs/",
        "docs/agent-coordination/sovereign-stack-performance.md",
        "docs/agent-coordination/sovereign-router-t2-t3.md",
        "docs/agent-coordination/GROK-HERMES-MASTER-PLAN.md",
        "Session-Health-Log.md",
        "INDEX.md",
    ],
}

SECRET_GLOBS = {".env", ".env.local", "secrets/", "auth.json"}


def log(msg: str) -> None:
    print(msg, flush=True)


def run_git(args: List[str], cwd: str, timeout: int = 30) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return 1, "", str(exc)


def _is_secret_path(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    for pat in SECRET_GLOBS:
        if pat.endswith("/"):
            if f"/{pat}" in f"/{low}/" or low.startswith(pat):
                return True
        elif low.endswith(pat) or low == pat:
            return True
    return False


def backup_repo(name: str, repo_dir: str, branch: str) -> None:
    log(f"\n## {name} Backup")
    root = Path(repo_dir)
    if not root.is_dir():
        log(f"SKIP {name}: directory missing")
        if name != "PhronesisSilo":
            ERRORS.append(f"{name} dir missing")
        return

    # 1) Tracked file updates
    run_git(["add", "-u"], repo_dir, timeout=20)

    # 2) Allowlist new files
    staged_allow = 0
    for rel in ALLOWLIST.get(repo_dir, []):
        target = root / rel
        if not target.exists():
            continue
        code, out, err = run_git(["add", "--", rel], repo_dir, timeout=30)
        if code != 0 and err:
            log(f"  allowlist add warn {rel}: {err[:120]}")

    # 3) Drift report (untracked outside allowlist — informational)
    _, status_out, _ = run_git(["status", "--porcelain"], repo_dir, timeout=15)
    untracked: List[str] = []
    for line in (status_out or "").splitlines():
        if line.startswith("??"):
            path = line[3:].strip()
            if not _is_secret_path(path):
                untracked.append(path)
    if untracked:
        log(f"  untracked (sample {min(5, len(untracked))}/{len(untracked)}):")
        for u in untracked[:5]:
            log(f"    ?? {u}")

    _, status_out, _ = run_git(["status", "--porcelain"], repo_dir, timeout=15)
    if not status_out:
        log(f"OK {name}: no changes to commit")
        return

    code, _, err = run_git(["commit", "-m", f"auto-backup {TS}"], repo_dir, timeout=20)
    if code != 0:
        if "nothing to commit" in err.lower():
            log(f"OK {name}: nothing to commit")
            return
        log(f"WARN {name} commit: {err[:200]}")
        ERRORS.append(f"{name} commit: {err[:80]}")
        return

    code, out, err = run_git(["push", "origin", branch], repo_dir, timeout=45)
    if code == 0:
        log(f"OK {name} pushed: {(out or 'ok')[:100]}")
    else:
        log(f"WARN {name} push: {err[:200]}")
        ERRORS.append(f"{name} push failed: {err[:80]}")


def main() -> None:
    log(f"## Resilience Backup v3 {TS}")
    backup_repo("PhronesisVault", r"D:\PhronesisVault", "master")
    backup_repo("HermesData", r"D:\HermesData", "main")
    # PhronesisSilo: actual under Phronesis-Sovereign; fall back
    silo_candidate = r"K:\Phronesis-Sovereign\Personal-Digital-Silo"
    if os.path.isdir(silo_candidate):
        backup_repo("PhronesisSilo", silo_candidate, "main")
    else:
        backup_repo("PhronesisSilo", r"K:\PhronesisSilo", "main")

    log("\n## Summary")
    if ERRORS:
        log(f"ISSUES: {len(ERRORS)}")
        for e in ERRORS:
            log(f"  - {e}")
        print(f"\n[ISSUES: {len(ERRORS)}]")
    else:
        log("All repos backed up successfully")
        print("\n[OK]")


if __name__ == "__main__":
    main()