#!/usr/bin/env python3
"""Resilience backup orchestrator — runs via no_agent cron every 4h.

v6 - git allowlist backup (HermesData + PhronesisVault) + optional K mirror
+ health alarm receipt. Never commits .env/secrets/sqlite.

Phases:
  A) git commit/push allowlisted paths (HEAD + stable branch)
  B) backup_k_mirror_once (selective K: mirror + hermes --quick)
  C) backup_health_alarm (color + receipt; --notify if not GREEN)

Env:
  BACKUP_SKIP_K=1       skip K mirror phase
  BACKUP_SKIP_ALARM=1   skip health alarm
  BACKUP_K_TIMEOUT=900  seconds for K phase subprocess
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TS = datetime.now().strftime("%Y%m%d-%H%M%S")
ERRORS: List[str] = []
PHASES: Dict[str, object] = {}
HERMES = Path(r"D:\HermesData")
STATE = HERMES / "state" / "backup_resilience_last.json"
SCRIPTS = HERMES / "scripts"

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
BLOCK_SUFFIXES = (
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".db-wal",
    ".db-shm",
)


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


GIT_ADD_U_TIMEOUT = 25
GIT_ADD_PATH_TIMEOUT = 20
GIT_STATUS_TIMEOUT = 20
GIT_COMMIT_TIMEOUT = 25
GIT_PUSH_TIMEOUT_DEFAULT = 50
GIT_PUSH_TIMEOUT_VAULT = 110


def _is_secret_path(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    for pat in SECRET_GLOBS:
        if pat.endswith("/"):
            if f"/{pat}" in f"/{low}/" or low.startswith(pat):
                return True
        elif low.endswith(pat) or low == pat:
            return True
    return False


def _is_blocked_blob(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    return any(low.endswith(suf) for suf in BLOCK_SUFFIXES)


def _current_branch(repo_dir: str) -> Optional[str]:
    code, out, err = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir, timeout=15)
    if code != 0 or not out or out == "HEAD":
        return None
    return out.strip()


def _push(repo_dir: str, branch: str, timeout: int) -> None:
    code, out, err = run_git(["push", "origin", branch], repo_dir, timeout=timeout)
    if code == 0:
        log(f"OK push origin/{branch}: {(out or 'ok')[:120]}")
        return
    msg = err or out or f"code={code}"
    log(f"WARN push origin/{branch} soft-fail: {msg[:220]}")
    ERRORS.append(f"push {branch}: {msg[:80]}")


def backup_repo(name: str, repo_dir: str, stable_branch: str) -> None:
    log(f"\n## {name} Backup")
    root = Path(repo_dir)
    if not root.is_dir():
        log(f"SKIP {name}: directory missing")
        if name != "PhronesisSilo":
            ERRORS.append(f"{name} dir missing")
        return

    cur = _current_branch(repo_dir)
    log(f"branch HEAD={cur or '?'} stable={stable_branch}")

    code, _, err = run_git(["add", "-u"], repo_dir, timeout=GIT_ADD_U_TIMEOUT)
    if code == 124:
        log(f"WARN {name}: git add -u timeout - skip repo to stay under cron cap")
        ERRORS.append(f"{name} add -u timeout")
        return

    # Unstage blocked blobs if add -u picked them up
    code, staged, _ = run_git(["diff", "--cached", "--name-only"], repo_dir, timeout=GIT_STATUS_TIMEOUT)
    if code == 0 and staged:
        for rel in staged.splitlines():
            if _is_blocked_blob(rel) or _is_secret_path(rel):
                run_git(["reset", "-q", "HEAD", "--", rel], repo_dir, timeout=15)
                log(f"  unstaged blocked {rel}")

    for rel in ALLOWLIST.get(repo_dir, [])[:40]:
        target = root / rel
        if not target.exists():
            continue
        if _is_secret_path(rel) or _is_blocked_blob(rel):
            continue
        code, out, err = run_git(["add", "--", rel], repo_dir, timeout=GIT_ADD_PATH_TIMEOUT)
        if code != 0 and err and code != 124:
            log(f"  allowlist add warn {rel}: {err[:120]}")

    # Second pass unstage blocked under allowlisted dirs (e.g. Operations/*.sqlite)
    code, staged, _ = run_git(["diff", "--cached", "--name-only"], repo_dir, timeout=GIT_STATUS_TIMEOUT)
    if code == 0 and staged:
        for rel in staged.splitlines():
            if _is_blocked_blob(rel) or _is_secret_path(rel):
                run_git(["reset", "-q", "HEAD", "--", rel], repo_dir, timeout=15)
                log(f"  unstaged blocked {rel}")

    code, status_out, err = run_git(
        ["diff", "--cached", "--name-only"], repo_dir, timeout=GIT_STATUS_TIMEOUT
    )
    if code == 124:
        log(f"WARN {name}: status timeout")
        ERRORS.append(f"{name} status timeout")
        return
    if (status_out or "").strip():
        code, _, err = run_git(
            ["commit", "-m", f"auto-backup {TS}"],
            repo_dir,
            timeout=GIT_COMMIT_TIMEOUT,
        )
        if code != 0:
            if "nothing to commit" in (err or "").lower():
                log(f"OK {name}: nothing to commit")
            else:
                log(f"WARN {name} commit: {err[:200]}")
                ERRORS.append(f"{name} commit: {err[:80]}")
                return
        else:
            log(f"OK {name} committed on {cur or 'HEAD'}")
    else:
        log(f"OK {name}: nothing staged to commit")

    push_timeout = (
        GIT_PUSH_TIMEOUT_VAULT if "PhronesisVault" in name else GIT_PUSH_TIMEOUT_DEFAULT
    )

    if cur:
        _push(repo_dir, cur, push_timeout)

    if stable_branch and stable_branch != cur:
        code, _, _ = run_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{stable_branch}"],
            repo_dir,
            timeout=10,
        )
        if code == 0:
            _push(repo_dir, stable_branch, push_timeout)
        else:
            log(f"OK {name}: no local branch {stable_branch} (skip stable push)")


def _run_phase(label: str, script: Path, extra_args: List[str] | None = None, timeout: int = 600) -> None:
    if not script.exists():
        ERRORS.append(f"{label}: missing {script.name}")
        PHASES[label] = {"ok": False, "error": "missing"}
        return
    cmd = [sys.executable, str(script), *(extra_args or [])]
    log(f"\n## Phase {label}: {script.name}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(HERMES))
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if out:
            # tail for cron logs
            for line in out.splitlines()[-40:]:
                log(f"  {line}")
        PHASES[label] = {"ok": r.returncode in (0, 2), "rc": r.returncode}
        if r.returncode not in (0, 2):
            ERRORS.append(f"{label} rc={r.returncode}")
    except subprocess.TimeoutExpired:
        ERRORS.append(f"{label} timeout")
        PHASES[label] = {"ok": False, "error": "timeout"}
        log(f"WARN {label} timeout after {timeout}s")
    except Exception as exc:
        ERRORS.append(f"{label}: {exc}")
        PHASES[label] = {"ok": False, "error": str(exc)}


def _write_receipt(ok: bool) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "errors": ERRORS[:20],
        "error_count": len(ERRORS),
        "phases": PHASES,
        "version": 6,
    }
    try:
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"WARN receipt write: {exc}")


def main() -> int:
    log(f"## Resilience Backup v6 {TS}")
    PHASES["git"] = {"started": True}
    backup_repo("PhronesisVault", r"D:\PhronesisVault", "master")
    backup_repo("HermesData", r"D:\HermesData", "main")
    silo_candidate = r"K:\Phronesis-Sovereign\Personal-Digital-Silo"
    if os.path.isdir(silo_candidate) and os.path.isdir(os.path.join(silo_candidate, ".git")):
        backup_repo("PhronesisSilo", silo_candidate, "main")
    else:
        log("\n## PhronesisSilo Backup")
        log("OK PhronesisSilo: skip git (bulk silo - K mirror + cloud recovery pack)")
    PHASES["git"] = {"ok": True, "errors_so_far": len(ERRORS)}

    if os.environ.get("BACKUP_SKIP_K") == "1":
        log("\n## Phase K: skipped (BACKUP_SKIP_K=1)")
        PHASES["k_mirror"] = {"ok": True, "skipped": True}
    else:
        k_timeout = int(os.environ.get("BACKUP_K_TIMEOUT", "900"))
        _run_phase("k_mirror", SCRIPTS / "backup_k_mirror_once.py", timeout=k_timeout)

    if os.environ.get("BACKUP_SKIP_ALARM") == "1":
        log("\n## Phase alarm: skipped")
        PHASES["alarm"] = {"ok": True, "skipped": True}
    else:
        _run_phase(
            "alarm",
            SCRIPTS / "backup_health_alarm.py",
            extra_args=["--notify", "--json"],
            timeout=120,
        )

    log("\n## Summary")
    ok = len(ERRORS) == 0
    if ERRORS:
        log(f"SOFT_ISSUES: {len(ERRORS)} (exit 0 - cron stays green; alarm carries color)")
        for e in ERRORS:
            log(f"  - {e}")
        print(f"\n[SOFT_ISSUES: {len(ERRORS)}]")
        _write_receipt(False)
    else:
        log("All phases completed without errors")
        print("\n[OK]")
        _write_receipt(True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
