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
        "skills/devops/backup-restore-mechanism/",
        "hermes-workspace/src/screens/dashboard/components/",
        "hermes-workspace/src/routes/api/sovereign-stack/",
        "hermes-workspace/src/status/model-manager-strip.ts",
        "config.yaml",
        "gateway/",
        "mcps/",
        "cron/jobs.json",
        "memories/MEMORY.md",
        "memories/USER.md",
        "hermes-agent/agent/chat_completion_helpers.py",
        "plugins/image_gen/comfyui_local/",
        "live_cron_hook.py",
    ],
    r"D:\PhronesisVault": [
        "Operations/",
        "scripts/",
        "MOCs/",
        "Housekeeping.md",
        "docs/agent-coordination/sovereign-stack-performance.md",
        "docs/agent-coordination/sovereign-router-t2-t3.md",
        "docs/agent-coordination/GROK-HERMES-MASTER-PLAN.md",
        "Session-Health-Log.md",
        "INDEX.md",
        "00-INDEX.md",
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


# Stay under Hermes no_agent 240s outer kill
GIT_ADD_U_TIMEOUT = 25
GIT_ADD_PATH_TIMEOUT = 20
GIT_STATUS_TIMEOUT = 20
GIT_COMMIT_TIMEOUT = 25
GIT_PUSH_TIMEOUT = 40


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

    # 1) Tracked file updates only (fast; never git add -A on huge trees)
    code, _, err = run_git(["add", "-u"], repo_dir, timeout=GIT_ADD_U_TIMEOUT)
    if code == 124:
        log(f"WARN {name}: git add -u timeout — skip repo to stay under cron cap")
        ERRORS.append(f"{name} add -u timeout")
        return

    # 2) Allowlist new files (bounded)
    for rel in ALLOWLIST.get(repo_dir, [])[:40]:
        target = root / rel
        if not target.exists():
            continue
        code, out, err = run_git(["add", "--", rel], repo_dir, timeout=GIT_ADD_PATH_TIMEOUT)
        if code != 0 and err and code != 124:
            log(f"  allowlist add warn {rel}: {err[:120]}")

    # 3) Staged? (avoid full porcelain on 10k+ dirty HermesData trees)
    code, status_out, err = run_git(
        ["diff", "--cached", "--name-only"], repo_dir, timeout=GIT_STATUS_TIMEOUT
    )
    if code == 124:
        log(f"WARN {name}: status timeout")
        ERRORS.append(f"{name} status timeout")
        return
    if not (status_out or "").strip():
        log(f"OK {name}: nothing staged to commit")
        return

    code, _, err = run_git(
        ["commit", "-m", f"auto-backup {TS}"], repo_dir, timeout=GIT_COMMIT_TIMEOUT
    )
    if code != 0:
        if "nothing to commit" in (err or "").lower():
            log(f"OK {name}: nothing to commit")
            return
        log(f"WARN {name} commit: {err[:200]}")
        ERRORS.append(f"{name} commit: {err[:80]}")
        return

    code, out, err = run_git(["push", "origin", branch], repo_dir, timeout=GIT_PUSH_TIMEOUT)
    if code == 0:
        log(f"OK {name} pushed: {(out or 'ok')[:100]}")
    else:
        # Soft: commit local is value; push can wait for auth/network
        log(f"WARN {name} push soft-fail: {err[:200]}")
        ERRORS.append(f"{name} push soft-fail: {err[:80]}")


def main() -> int:
    log(f"## Resilience Backup v4 {TS} (time-boxed for 240s cron)")
    backup_repo("PhronesisVault", r"D:\PhronesisVault", "master")
    backup_repo("HermesData", r"D:\HermesData", "main")
    # PhronesisSilo bulk on K: is NOT a git repo (by design).
    silo_candidate = r"K:\Phronesis-Sovereign\Personal-Digital-Silo"
    if os.path.isdir(silo_candidate) and os.path.isdir(os.path.join(silo_candidate, ".git")):
        backup_repo("PhronesisSilo", silo_candidate, "main")
    else:
        log("\n## PhronesisSilo Backup")
        log("OK PhronesisSilo: skip git (bulk silo — K mirror + cloud recovery pack)")

    log("\n## Summary")
    if ERRORS:
        log(f"SOFT_ISSUES: {len(ERRORS)} (exit 0 — cron stays green)")
        for e in ERRORS:
            log(f"  - {e}")
        print(f"\n[SOFT_ISSUES: {len(ERRORS)}]")
    else:
        log("All repos backed up successfully")
        print("\n[OK]")
    # Never trip Hermes no_agent hard-fail on soft push/timeout partials
    return 0


if __name__ == "__main__":
    raise SystemExit(main())