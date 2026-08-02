#!/usr/bin/env python3
"""PREPARE (not execute force-push) vault history purge of session_state.sqlite.

Jeff gate required for --execute-filter and --force-push-master.

Default mode: analyze + write a runbook + optional clone for filter-repo.
Installs git-filter-repo via pip if missing when --install-tools.

Usage:
  python D:/HermesData/scripts/vault_history_sqlite_purge_prepare.py
  python D:/HermesData/scripts/vault_history_sqlite_purge_prepare.py --install-tools
  python D:/HermesData/scripts/vault_history_sqlite_purge_prepare.py --execute-filter
      # rewrites ONLY a clone under D:/HermesData/tmp/vault-filter-work
  python ... --execute-filter --force-push-master
      # REQUIRES env CONFIRM_VAULT_FORCE_PUSH=YES
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
WORK = HERMES / "tmp" / "vault-filter-work"
STATE = HERMES / "state" / "vault_history_purge_prepare_last.json"
RUNBOOK = VAULT / "Operations" / "Vault-GitHub-History-Purge-Runbook-2026-08-01.md"
POISON = "Operations/session_state.sqlite"


def run(cmd: List[str], cwd: Path | None = None, timeout: int = 120) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install-tools", action="store_true")
    ap.add_argument("--execute-filter", action="store_true", help="run filter-repo on CLONE only")
    ap.add_argument("--force-push-master", action="store_true", help="needs CONFIRM_VAULT_FORCE_PUSH=YES")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).isoformat()
    notes: List[str] = []
    errors: List[str] = []

    # Analyze poison in live repo (read-only)
    code, out, err = run(
        ["git", "-C", str(VAULT), "rev-list", "--objects", "--all"],
        timeout=180,
    )
    poison_commits = 0
    if code == 0:
        # cheaper: log --all -- path
        c2, o2, _ = run(
            ["git", "-C", str(VAULT), "log", "--oneline", "--", POISON],
            timeout=120,
        )
        poison_commits = len(o2.splitlines()) if o2 else 0
        notes.append(f"commits_touching_poison={poison_commits}")
    else:
        errors.append(f"rev-list: {err or out}")

    c3, o3, _ = run(["git", "-C", str(VAULT), "rev-list", "--left-right", "--count", "origin/master...master"], timeout=30)
    notes.append(f"origin_master_vs_master={o3}")

    filter_ok = False
    if args.install_tools:
        c, so, se = run([sys.executable, "-m", "pip", "install", "--user", "git-filter-repo"], timeout=180)
        notes.append(f"pip_git_filter_repo_rc={c}")
        if c != 0:
            errors.append(f"pip install failed: {se or so}")

    # detect filter-repo
    c, so, se = run([sys.executable, "-c", "import git_filter_repo; print(git_filter_repo.__file__)"], timeout=30)
    has_fr = c == 0
    notes.append(f"git_filter_repo={has_fr} {so[:80] if so else ''}")

    if args.execute_filter:
        if not has_fr:
            errors.append("git_filter_repo not importable; pass --install-tools first")
        else:
            if WORK.exists():
                shutil.rmtree(WORK, ignore_errors=True)
            WORK.parent.mkdir(parents=True, exist_ok=True)
            log_clone = run(["git", "clone", str(VAULT), str(WORK)], timeout=600)
            if log_clone[0] != 0:
                errors.append(f"clone work: {log_clone[2] or log_clone[1]}")
            else:
                # filter-repo refuses non-fresh clones unless --force
                c, so, se = run(
                    [
                        sys.executable,
                        "-m",
                        "git_filter_repo",
                        "--force",
                        "--invert-paths",
                        "--path",
                        POISON,
                        "--path-glob",
                        "*.sqlite",
                    ],
                    cwd=WORK,
                    timeout=1800,
                )
                notes.append(f"filter_repo_rc={c}")
                if c != 0:
                    errors.append(f"filter-repo: {(se or so)[:300]}")
                else:
                    filter_ok = True
                    notes.append("filter_ok_on_clone")
                    # size check
                    c2, o2, _ = run(
                        ["git", "-C", str(WORK), "rev-list", "--objects", "--all"],
                        timeout=300,
                    )
                    # push?
                    if args.force_push_master:
                        if os.environ.get("CONFIRM_VAULT_FORCE_PUSH") != "YES":
                            errors.append(
                                "refusing force-push: set CONFIRM_VAULT_FORCE_PUSH=YES"
                            )
                        else:
                            run(
                                [
                                    "git",
                                    "-C",
                                    str(WORK),
                                    "remote",
                                    "add",
                                    "origin",
                                    "https://github.com/CowNinja/PhronesisVault.git",
                                ],
                                timeout=30,
                            )
                            # may already have origin from clone
                            run(
                                [
                                    "git",
                                    "-C",
                                    str(WORK),
                                    "remote",
                                    "set-url",
                                    "origin",
                                    "https://github.com/CowNinja/PhronesisVault.git",
                                ],
                                timeout=30,
                            )
                            c3, so3, se3 = run(
                                [
                                    "git",
                                    "-C",
                                    str(WORK),
                                    "push",
                                    "origin",
                                    "--force",
                                    "--all",
                                ],
                                timeout=600,
                            )
                            notes.append(f"force_push_all_rc={c3}")
                            if c3 != 0:
                                errors.append(f"force_push: {(se3 or so3)[:300]}")

    runbook = f"""# Vault GitHub History Purge Runbook - 2026-08-01

**Status:** prepare-only unless Jeff sets `CONFIRM_VAULT_FORCE_PUSH=YES`  
**Poison path:** `{POISON}` (multiple 100MB+ blobs in history)  
**Measured:** commits_touching_poison{poison_commits}  origin/master vs master: `{o3}`  
**Prepared:** {ts}

## Research basis

- GitHub hard-blocks blobs **>100MB**; warning at 50MB ([GitHub docs: large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)).
- **git-filter-repo** is the maintained replacement for filter-branch/BFG for path stripping ([newren/git-filter-repo](https://github.com/newren/git-filter-repo)).
- Always rewrite a **fresh clone**, verify, then force-push; notify any other clones.
- Prefer **not** committing runtime DBs; gitignore `*.sqlite*` (already done on tip).

## Interim (already automated - no force-push)

```text
python D:/HermesData/scripts/vault_github_clean_mirror_push.py
```

Pushes shallow clean tip to branch `github-cns-mirror`.

## Full purge (Jeff at keyboard)

```text
python D:/HermesData/scripts/vault_history_sqlite_purge_prepare.py --install-tools
python D:/HermesData/scripts/vault_history_sqlite_purge_prepare.py --execute-filter
# inspect D:/HermesData/tmp/vault-filter-work
set CONFIRM_VAULT_FORCE_PUSH=YES
python D:/HermesData/scripts/vault_history_sqlite_purge_prepare.py --execute-filter --force-push-master
```

After force-push:

1. Re-clone or reset local vault carefully (SHAs changed).
2. `python D:/HermesData/scripts/backup-resilience.py`
3. `python D:/HermesData/scripts/backup_health_alarm.py --json`
4. Prefer `master` or merge `github-cns-mirror` strategy as needed.

## Do not

- Force-push unattended
- git add -A on vault
- Re-commit session_state.sqlite

[[Operations/Backup-Architecture-Audit-2026-08-01]]
"""
    try:
        RUNBOOK.parent.mkdir(parents=True, exist_ok=True)
        RUNBOOK.write_text(runbook, encoding="utf-8")
        notes.append(f"runbook={RUNBOOK}")
    except Exception as e:
        errors.append(f"runbook write: {e}")

    payload = {
        "ts": ts,
        "ok": len(errors) == 0,
        "filter_ok_on_clone": filter_ok,
        "notes": notes,
        "errors": errors,
        "execute_filter": args.execute_filter,
        "force_push_requested": args.force_push_master,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
