#!/usr/bin/env python3
"""Resilience backup orchestrator — no_agent cron every 4h.

v7 cadence (Jeff 2026-08-01):
  A) git allowlist commit+push HermesData only (vault master push skipped — poison history)
  B) k_resilience_layout_once (dirs + fossil quarantine)
  C) backup_critical_state_zip (replaces hanging hermes --quick)
  D) backup_k_mirror_once (D->K selective slices)
  E) backup_k_silo_life_mirror_once (budgeted silo signal)
  F) vault_github_clean_mirror_push --if-due --min-hours 12  (~2x/day when dirty)
  G) cloud_recovery_pack_sync (best-effort)
  H) backup_health_alarm --notify

Env:
  BACKUP_SKIP_K=1
  BACKUP_SKIP_ALARM=1
  BACKUP_SKIP_VAULT_MIRROR=1
  BACKUP_SKIP_SILO=1
  BACKUP_SKIP_CLOUD=1
  BACKUP_K_TIMEOUT=900
  BACKUP_VAULT_MIRROR_MIN_HOURS=12
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

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
        "config.yaml",
        "gateway/",
        "mcps/",
        "cron/jobs.json",
        "memories/MEMORY.md",
        "memories/USER.md",
        "live_cron_hook.py",
        "plugins/image_gen/comfyui_local/",
    ],
    r"D:\PhronesisVault": [
        "Operations/",
        "scripts/",
        "MOCs/",
        "Housekeeping.md",
        "INDEX.md",
        "00-INDEX.md",
        "Session-Health-Log.md",
    ],
}

SECRET_GLOBS = {".env", ".env.local", "secrets/", "auth.json"}
BLOCK_SUFFIXES = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")

GIT_ADD_U_TIMEOUT = 25
GIT_ADD_PATH_TIMEOUT = 20
GIT_STATUS_TIMEOUT = 20
GIT_COMMIT_TIMEOUT = 25
GIT_PUSH_TIMEOUT_DEFAULT = 50


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


def _blocked(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    if any(s in low for s in SECRET_GLOBS):
        return True
    return any(low.endswith(suf) for suf in BLOCK_SUFFIXES)


def _push(repo_dir: str, branch: str, timeout: int) -> None:
    code, out, err = run_git(["push", "origin", branch], repo_dir, timeout=timeout)
    if code != 0:
        msg = (err or out or f"rc={code}")[:180]
        ERRORS.append(f"push {branch}: {msg}")
        log(f"WARN push {branch}: {msg}")
    else:
        log(f"OK pushed origin/{branch}")


def backup_repo(name: str, repo_dir: str, stable_branch: str | None, push: bool = True) -> None:
    log(f"\n## {name} Backup")
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        log(f"SKIP {name}: not a git repo")
        return
    paths = ALLOWLIST.get(repo_dir, [])
    run_git(["add", "-u"], repo_dir, timeout=GIT_ADD_U_TIMEOUT)
    for p in paths:
        run_git(["add", "--", p], repo_dir, timeout=GIT_ADD_PATH_TIMEOUT)

    # unstage blocked
    code, staged, _ = run_git(["diff", "--cached", "--name-only"], repo_dir, timeout=15)
    if code == 0 and staged:
        for line in staged.splitlines():
            if _blocked(line):
                run_git(["reset", "-q", "HEAD", "--", line], repo_dir, timeout=10)
                log(f"  unstage blocked {line}")

    code, status, _ = run_git(["status", "--porcelain"], repo_dir, timeout=GIT_STATUS_TIMEOUT)
    code2, cur, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir, timeout=10)
    cur = cur if code2 == 0 else ""

    code3, diff_c, _ = run_git(["diff", "--cached", "--name-only"], repo_dir, timeout=15)
    if code3 == 0 and diff_c.strip():
        msg = f"resilience-backup {TS} {name}"
        c, so, se = run_git(["commit", "-m", msg], repo_dir, timeout=GIT_COMMIT_TIMEOUT)
        if c != 0:
            if "nothing to commit" not in (so + se).lower():
                ERRORS.append(f"{name} commit: {(se or so)[:120]}")
                return
        else:
            log(f"OK {name} committed on {cur or 'HEAD'}")
    else:
        log(f"OK {name}: nothing staged to commit")

    if not push:
        log(f"OK {name}: local commit only (push disabled — use clean mirror for offsite)")
        return

    if cur:
        _push(repo_dir, cur, GIT_PUSH_TIMEOUT_DEFAULT)
    if stable_branch and stable_branch != cur:
        code, _, _ = run_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{stable_branch}"],
            repo_dir,
            timeout=10,
        )
        if code == 0:
            _push(repo_dir, stable_branch, GIT_PUSH_TIMEOUT_DEFAULT)


def _run_phase(label: str, script: Path, extra_args: List[str] | None = None, timeout: int = 600) -> None:
    if not script.exists():
        ERRORS.append(f"{label}: missing {script.name}")
        PHASES[label] = {"ok": False, "error": "missing"}
        return
    cmd = [sys.executable, str(script), *(extra_args or [])]
    log(f"\n## Phase {label}: {script.name} {' '.join(extra_args or [])}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(HERMES))
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if out:
            for line in out.splitlines()[-40:]:
                log(f"  {line}")
        # rc 0 or 2 (skipped/advisory) ok
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
        "version": 7,
        "cadence": {
            "k_hours": 4,
            "hermesdata_git_hours": 4,
            "vault_clean_mirror_min_hours": float(
                os.environ.get("BACKUP_VAULT_MIRROR_MIN_HOURS", "12")
            ),
        },
    }
    try:
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"WARN receipt write: {exc}")


def main() -> int:
    log(f"## Resilience Backup v7 {TS}")

    # A) git — HermesData pushes; vault local-only (offsite = clean mirror)
    PHASES["git"] = {"started": True}
    backup_repo("HermesData", r"D:\HermesData", "main", push=True)
    backup_repo("PhronesisVault", r"D:\PhronesisVault", None, push=False)
    PHASES["git"] = {"ok": True, "errors_so_far": len(ERRORS)}

    # B) K layout / fossil quarantine (idempotent; was 120s — bump + one retry)
    _run_phase(
        "k_layout",
        SCRIPTS / "k_resilience_layout_once.py",
        extra_args=["--json"],
        timeout=300,
    )
    if not (PHASES.get("k_layout") or {}).get("ok"):
        log("RETRY k_layout once")
        # clear sticky error label for clean receipt if retry works
        ERRORS[:] = [e for e in ERRORS if not str(e).startswith("k_layout")]
        _run_phase(
            "k_layout",
            SCRIPTS / "k_resilience_layout_once.py",
            extra_args=["--json"],
            timeout=300,
        )

    # C) critical zip
    _run_phase("critical_zip", SCRIPTS / "backup_critical_state_zip.py", extra_args=["--json"], timeout=180)

    # D) K hermes/vault slices
    if os.environ.get("BACKUP_SKIP_K") == "1":
        log("\n## Phase K: skipped")
        PHASES["k_mirror"] = {"ok": True, "skipped": True}
    else:
        k_timeout = int(os.environ.get("BACKUP_K_TIMEOUT", "900"))
        _run_phase("k_mirror", SCRIPTS / "backup_k_mirror_once.py", timeout=k_timeout)

    # E) silo signal
    if os.environ.get("BACKUP_SKIP_SILO") == "1":
        PHASES["silo_signal"] = {"ok": True, "skipped": True}
    else:
        _run_phase(
            "silo_signal",
            SCRIPTS / "backup_k_silo_life_mirror_once.py",
            extra_args=["--json"],
            timeout=600,
        )

    # F) vault GitHub clean mirror ~2x/day
    if os.environ.get("BACKUP_SKIP_VAULT_MIRROR") == "1":
        PHASES["vault_clean_mirror"] = {"ok": True, "skipped": True}
    else:
        min_h = os.environ.get("BACKUP_VAULT_MIRROR_MIN_HOURS", "12")
        _run_phase(
            "vault_clean_mirror",
            SCRIPTS / "vault_github_clean_mirror_push.py",
            extra_args=["--if-due", "--min-hours", str(min_h)],
            timeout=600,
        )

    # G) cloud pack
    if os.environ.get("BACKUP_SKIP_CLOUD") != "1":
        _run_phase(
            "cloud_pack",
            SCRIPTS / "cloud_recovery_pack_sync.py",
            timeout=180,
        )
    else:
        PHASES["cloud_pack"] = {"ok": True, "skipped": True}

    # H) write receipt BEFORE alarm so health sees this cycle
    soft = len(ERRORS) > 0
    _write_receipt(ok=not soft)

    # I) health (reads receipt)
    if os.environ.get("BACKUP_SKIP_ALARM") == "1":
        PHASES["alarm"] = {"ok": True, "skipped": True}
    else:
        _run_phase(
            "alarm",
            SCRIPTS / "backup_health_alarm.py",
            extra_args=["--notify", "--json"],
            timeout=120,
        )
        # refresh receipt with alarm phase
        _write_receipt(ok=(len(ERRORS) == 0))

    log("\n## Summary")
    if ERRORS:
        log(f"SOFT_ISSUES: {len(ERRORS)} (exit 0; alarm carries color)")
        for e in ERRORS:
            log(f"  - {e}")
        print(f"\n[SOFT_ISSUES: {len(ERRORS)}]")
    else:
        log("All phases completed without errors")
        print("\n[OK]")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
