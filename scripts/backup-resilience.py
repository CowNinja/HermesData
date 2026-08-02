#!/usr/bin/env python3
"""Resilience backup orchestrator — no_agent cron every 4h.

v9 cadence (2026-08-02 cook — silo hang fix + soft phase policy + K baby automations):
  A) git allowlist commit+push HermesData only (vault master local-only; offsite=cns-mirror)
  B) k_resilience_layout_once (dirs + fossil quarantine)
  C) backup_critical_state_zip (replaces hanging hermes --quick)
  D) backup_k_mirror_once (D->K selective slices)
  E) backup_k_silo_life_mirror_once v3 (wall-clock budget + lock; soft if prior fresh)
  F) vault_github_clean_mirror_push --if-due --min-hours 12
  G) cloud_recovery_pack_sync (best-effort soft)
  H) k_free_space_governor
  I) vault_poison_recurrence_guard
  J) k_inventory_snapshot (fast top-level)
  K) k_fossil_reappearance_scan (no delete)
  L) k_manifest_root_write
  M) backup_phase_policy + receipt
  N) backup_health_alarm --notify
  O) backup_restore_drill auto if last >7d OR BACKUP_RUN_DRILL=1

Env:
  BACKUP_SKIP_K=1
  BACKUP_SKIP_ALARM=1
  BACKUP_SKIP_VAULT_MIRROR=1
  BACKUP_SKIP_SILO=1
  BACKUP_SKIP_CLOUD=1
  BACKUP_SKIP_GOVERNOR=1
  BACKUP_SKIP_POISON_GUARD=1
  BACKUP_SKIP_DRILL=1
  BACKUP_SKIP_INVENTORY=1
  BACKUP_SKIP_FOSSIL_SCAN=1
  BACKUP_K_TIMEOUT=900
  BACKUP_SILO_TIMEOUT=300
  BACKUP_SILO_BUDGET_SEC=240
  BACKUP_VAULT_MIRROR_MIN_HOURS=12
  BACKUP_RUN_DRILL=1
  BACKUP_DRILL_MAX_AGE_DAYS=7
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
SOFT_ERRORS: List[str] = []
PHASES: Dict[str, object] = {}
HERMES = Path(r"D:\HermesData")
STATE = HERMES / "state" / "backup_resilience_last.json"
SCRIPTS = HERMES / "scripts"
DRILL_STATE = HERMES / "state" / "backup_restore_drill_last.json"
LOCK = HERMES / "state" / "backup_resilience.lock"

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

# phases whose failures are soft by default (policy may still promote)
DEFAULT_SOFT_PHASES = {
    "silo_signal",
    "cloud_pack",
    "k_inventory",
    "fossil_scan",
    "restore_drill",
}


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

    code, staged, _ = run_git(["diff", "--cached", "--name-only"], repo_dir, timeout=15)
    if code == 0 and staged:
        for line in staged.splitlines():
            if _blocked(line):
                run_git(["reset", "-q", "HEAD", "--", line], repo_dir, timeout=10)
                log(f"  unstage blocked {line}")

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


def _run_phase(
    label: str,
    script: Path,
    extra_args: List[str] | None = None,
    timeout: int = 600,
    soft: bool | None = None,
) -> None:
    if soft is None:
        soft = label in DEFAULT_SOFT_PHASES
    if not script.exists():
        msg = f"{label}: missing {script.name}"
        (SOFT_ERRORS if soft else ERRORS).append(msg)
        PHASES[label] = {"ok": False, "error": "missing", "soft": soft}
        return
    cmd = [sys.executable, str(script), *(extra_args or [])]
    log(f"\n## Phase {label}: {script.name} {' '.join(extra_args or [])}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(HERMES))
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if out:
            for line in out.splitlines()[-40:]:
                log(f"  {line}")
        ok_rc = r.returncode in (0, 2)
        # silo lock busy (3) is soft if we have prior
        if label == "silo_signal" and r.returncode == 3:
            ok_rc = False
            soft = True
        PHASES[label] = {"ok": ok_rc, "rc": r.returncode, "soft": soft}
        if not ok_rc:
            msg = f"{label} rc={r.returncode}"
            (SOFT_ERRORS if soft else ERRORS).append(msg)
    except subprocess.TimeoutExpired:
        msg = f"{label} timeout"
        (SOFT_ERRORS if soft else ERRORS).append(msg)
        PHASES[label] = {"ok": False, "error": "timeout", "soft": soft}
        log(f"WARN {label} timeout after {timeout}s (soft={soft})")
    except Exception as exc:
        msg = f"{label}: {exc}"
        (SOFT_ERRORS if soft else ERRORS).append(msg)
        PHASES[label] = {"ok": False, "error": str(exc), "soft": soft}


def _apply_phase_policy() -> Dict[str, object]:
    """Merge ERRORS+SOFT via backup_phase_policy; may demote silo timeout to soft."""
    policy_script = SCRIPTS / "backup_phase_policy.py"
    all_errs = list(ERRORS) + list(SOFT_ERRORS)
    if not policy_script.exists() or not all_errs:
        return {
            "ok_for_receipt": len(ERRORS) == 0,
            "hard": list(ERRORS),
            "soft": list(SOFT_ERRORS),
        }
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(policy_script),
                "--errors-json",
                json.dumps(all_errs),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(HERMES),
        )
        data = json.loads(r.stdout or "{}")
        # rebuild ERRORS/SOFT from policy
        ERRORS.clear()
        SOFT_ERRORS.clear()
        ERRORS.extend(data.get("hard") or [])
        SOFT_ERRORS.extend(data.get("soft") or [])
        return data
    except Exception as exc:
        log(f"WARN phase_policy: {exc}")
        return {"ok_for_receipt": len(ERRORS) == 0, "error": str(exc)}


def _write_receipt(ok: bool, policy: Dict[str, object] | None = None) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "errors": ERRORS[:20],
        "soft_errors": SOFT_ERRORS[:20],
        "error_count": len(ERRORS),
        "soft_error_count": len(SOFT_ERRORS),
        "phases": PHASES,
        "policy": policy or {},
        "version": 9,
        "cadence": {
            "k_hours": 4,
            "hermesdata_git_hours": 4,
            "vault_clean_mirror_min_hours": float(
                os.environ.get("BACKUP_VAULT_MIRROR_MIN_HOURS", "12")
            ),
            "silo_budget_sec": int(os.environ.get("BACKUP_SILO_BUDGET_SEC", "240")),
            "drill_max_age_days": float(os.environ.get("BACKUP_DRILL_MAX_AGE_DAYS", "7")),
        },
    }
    try:
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"WARN receipt write: {exc}")


def _drill_due() -> bool:
    if os.environ.get("BACKUP_RUN_DRILL") == "1":
        return True
    max_days = float(os.environ.get("BACKUP_DRILL_MAX_AGE_DAYS", "7"))
    if not DRILL_STATE.exists():
        return True
    try:
        data = json.loads(DRILL_STATE.read_text(encoding="utf-8"))
        ts = data.get("ts") or ""
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_d = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        return age_d >= max_days
    except Exception:
        return True


def _acquire_resilience_lock() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            data = json.loads(LOCK.read_text(encoding="utf-8"))
            age = datetime.now().timestamp() - float(data.get("started") or 0)
            pid = int(data.get("pid") or 0)
            # if lock older than 2h, clear
            if age < 7200:
                # check pid
                try:
                    r = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if str(pid) in (r.stdout or "") and "No tasks" not in (r.stdout or ""):
                        log(f"SKIP resilience: already running pid={pid} age_s={age:.0f}")
                        return False
                except Exception:
                    pass
        except Exception:
            pass
    LOCK.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started": datetime.now().timestamp(),
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return True


def _release_resilience_lock() -> None:
    try:
        if LOCK.exists():
            data = json.loads(LOCK.read_text(encoding="utf-8"))
            if int(data.get("pid") or 0) == os.getpid():
                LOCK.unlink(missing_ok=True)
    except Exception:
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> int:
    log(f"## Resilience Backup v9 {TS}")
    if not _acquire_resilience_lock():
        # write busy receipt without clobbering last good ok if possible
        busy = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ok": True,
            "skipped": True,
            "reason": "lock_busy",
            "version": 9,
        }
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
            if prev.get("ok") is False:
                busy["ok"] = False
                busy["errors"] = prev.get("errors") or []
        except Exception:
            pass
        (HERMES / "state" / "backup_resilience_busy.json").write_text(
            json.dumps(busy, indent=2), encoding="utf-8"
        )
        print("\n[SKIP lock_busy]")
        return 0

    try:
        # A) git
        PHASES["git"] = {"started": True}
        backup_repo("HermesData", r"D:\HermesData", "main", push=True)
        backup_repo("PhronesisVault", r"D:\PhronesisVault", None, push=False)
        PHASES["git"] = {"ok": True, "errors_so_far": len(ERRORS)}

        # B) layout
        _run_phase(
            "k_layout",
            SCRIPTS / "k_resilience_layout_once.py",
            extra_args=["--json"],
            timeout=300,
            soft=False,
        )
        if not (PHASES.get("k_layout") or {}).get("ok"):
            log("RETRY k_layout once")
            ERRORS[:] = [e for e in ERRORS if not str(e).startswith("k_layout")]
            _run_phase(
                "k_layout",
                SCRIPTS / "k_resilience_layout_once.py",
                extra_args=["--json"],
                timeout=300,
                soft=False,
            )

        # C) critical zip
        _run_phase(
            "critical_zip",
            SCRIPTS / "backup_critical_state_zip.py",
            extra_args=["--json"],
            timeout=180,
            soft=False,
        )

        # D) K hermes/vault slices
        if os.environ.get("BACKUP_SKIP_K") == "1":
            log("\n## Phase K: skipped")
            PHASES["k_mirror"] = {"ok": True, "skipped": True}
        else:
            k_timeout = int(os.environ.get("BACKUP_K_TIMEOUT", "900"))
            _run_phase("k_mirror", SCRIPTS / "backup_k_mirror_once.py", timeout=k_timeout, soft=False)

        # E) silo signal v3 wall-clock
        if os.environ.get("BACKUP_SKIP_SILO") == "1":
            PHASES["silo_signal"] = {"ok": True, "skipped": True}
        else:
            silo_t = int(os.environ.get("BACKUP_SILO_TIMEOUT", "300"))
            budget = os.environ.get("BACKUP_SILO_BUDGET_SEC", "240")
            _run_phase(
                "silo_signal",
                SCRIPTS / "backup_k_silo_life_mirror_once.py",
                extra_args=["--json", "--budget-sec", str(budget)],
                timeout=silo_t,
                soft=True,
            )

        # F) vault clean mirror
        if os.environ.get("BACKUP_SKIP_VAULT_MIRROR") == "1":
            PHASES["vault_clean_mirror"] = {"ok": True, "skipped": True}
        else:
            min_h = os.environ.get("BACKUP_VAULT_MIRROR_MIN_HOURS", "12")
            _run_phase(
                "vault_clean_mirror",
                SCRIPTS / "vault_github_clean_mirror_push.py",
                extra_args=["--if-due", "--min-hours", str(min_h)],
                timeout=600,
                soft=False,
            )

        # G) cloud pack soft
        if os.environ.get("BACKUP_SKIP_CLOUD") != "1":
            _run_phase(
                "cloud_pack",
                SCRIPTS / "cloud_recovery_pack_sync.py",
                timeout=180,
                soft=True,
            )
        else:
            PHASES["cloud_pack"] = {"ok": True, "skipped": True}

        # H) governor
        if os.environ.get("BACKUP_SKIP_GOVERNOR") == "1":
            PHASES["k_governor"] = {"ok": True, "skipped": True}
        else:
            _run_phase(
                "k_governor",
                SCRIPTS / "k_free_space_governor.py",
                extra_args=["--json"],
                timeout=180,
                soft=False,
            )

        # I) poison guard
        if os.environ.get("BACKUP_SKIP_POISON_GUARD") == "1":
            PHASES["poison_guard"] = {"ok": True, "skipped": True}
        else:
            _run_phase(
                "poison_guard",
                SCRIPTS / "vault_poison_recurrence_guard.py",
                extra_args=["--json", "--fix-gitignore", "--unstage-blocked"],
                timeout=300,
                soft=False,
            )

        # J) inventory
        if os.environ.get("BACKUP_SKIP_INVENTORY") == "1":
            PHASES["k_inventory"] = {"ok": True, "skipped": True}
        else:
            _run_phase(
                "k_inventory",
                SCRIPTS / "k_inventory_snapshot.py",
                extra_args=["--json", "--deep-resilience"],
                timeout=180,
                soft=True,
            )

        # K) fossil scan (report only)
        if os.environ.get("BACKUP_SKIP_FOSSIL_SCAN") == "1":
            PHASES["fossil_scan"] = {"ok": True, "skipped": True}
        else:
            _run_phase(
                "fossil_scan",
                SCRIPTS / "k_fossil_reappearance_scan.py",
                extra_args=["--json", "--min-gb", "5"],
                timeout=180,
                soft=True,
            )

        # L) manifest root
        _run_phase("manifest_root", SCRIPTS / "k_manifest_root_write.py", timeout=60, soft=False)

        # M) policy + receipt before alarm
        policy = _apply_phase_policy()
        ok = bool(policy.get("ok_for_receipt", len(ERRORS) == 0))
        _write_receipt(ok=ok, policy=policy)

        # N) health
        if os.environ.get("BACKUP_SKIP_ALARM") == "1":
            PHASES["alarm"] = {"ok": True, "skipped": True}
        else:
            _run_phase(
                "alarm",
                SCRIPTS / "backup_health_alarm.py",
                extra_args=["--notify", "--json"],
                timeout=120,
                soft=False,
            )
            policy = _apply_phase_policy()
            ok = bool(policy.get("ok_for_receipt", len(ERRORS) == 0))
            _write_receipt(ok=ok, policy=policy)

        # O) restore drill weekly auto
        if os.environ.get("BACKUP_SKIP_DRILL") == "1":
            PHASES["restore_drill"] = {"ok": True, "skipped": True}
        elif _drill_due():
            _run_phase(
                "restore_drill",
                SCRIPTS / "backup_restore_drill.py",
                extra_args=["--json", "--stage"],
                timeout=180,
                soft=True,
            )
            policy = _apply_phase_policy()
            ok = bool(policy.get("ok_for_receipt", len(ERRORS) == 0))
            _write_receipt(ok=ok, policy=policy)
        else:
            PHASES["restore_drill"] = {"ok": True, "skipped": True, "reason": "fresh_within_7d"}

        log("\n## Summary")
        if ERRORS or SOFT_ERRORS:
            log(f"HARD={len(ERRORS)} SOFT={len(SOFT_ERRORS)} receipt_ok={ok}")
            for e in ERRORS:
                log(f"  HARD - {e}")
            for e in SOFT_ERRORS:
                log(f"  SOFT - {e}")
            print(f"\n[{'OK' if ok else 'SOFT_ISSUES'}: hard={len(ERRORS)} soft={len(SOFT_ERRORS)}]")
        else:
            log("All phases completed without errors")
            print("\n[OK]")
        return 0
    finally:
        _release_resilience_lock()


if __name__ == "__main__":
    raise SystemExit(main())
