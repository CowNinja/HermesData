#!/usr/bin/env python3
"""Self-recovery watchdog — unpushed-commit check + bounded auto-push.

Runs via Hermes cron every 30m (Self-Recovery-Watchdog job).
Never logs secret values. PS-pipe-safe summary line at end.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPOS: List[Tuple[str, Path, str]] = [
    ("HermesData", Path(r"D:\HermesData"), "main"),
    ("PhronesisVault", Path(r"D:\PhronesisVault"), "master"),
    ("PhronesisSilo", Path(r"K:\PhronesisSilo"), "main"),
]

PUSH_TIMEOUT_SEC = 45


def _run(cmd: List[str], cwd: Path, timeout: int = 30) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return 1, "", str(exc)


def _audit_repo(name: str, root: Path, branch: str) -> Dict[str, Any]:
    if not (root / ".git").is_dir():
        return {"name": name, "ok": False, "reason": "no_git", "path": str(root)}

    _, ahead_out, _ = _run(
        ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
        root,
        timeout=15,
    )
    _, dirty_out, _ = _run(["git", "status", "--porcelain"], root, timeout=15)
    _, remote_out, _ = _run(["git", "remote", "get-url", "origin"], root, timeout=10)

    try:
        ahead = int(ahead_out or "0")
    except ValueError:
        ahead = -1

    dirty_lines = [ln for ln in (dirty_out or "").splitlines() if ln.strip()]
    return {
        "name": name,
        "ok": True,
        "path": str(root),
        "branch": branch,
        "remote": remote_out or "",
        "unpushed": ahead,
        "dirty_count": len(dirty_lines),
        "dirty_sample": dirty_lines[:8],
    }


def _auto_push(name: str, root: Path, branch: str) -> Dict[str, Any]:
    code, out, err = _run(
        ["git", "push", "origin", branch],
        root,
        timeout=PUSH_TIMEOUT_SEC,
    )
    return {
        "name": name,
        "action": "push",
        "ok": code == 0,
        "code": code,
        "stdout": out[:200],
        "stderr": err[:200],
    }


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"## Self-Recovery-Watchdog {ts}")
    issues: List[str] = []
    actions: List[Dict[str, Any]] = []

    for name, root, branch in REPOS:
        audit = _audit_repo(name, root, branch)
        if not audit.get("ok"):
            print(f"SKIP {name}: {audit.get('reason')}")
            if name != "PhronesisSilo":
                issues.append(f"{name}: {audit.get('reason')}")
            continue

        unpushed = int(audit.get("unpushed") or 0)
        dirty = int(audit.get("dirty_count") or 0)
        print(
            f"{name}: unpushed={unpushed} dirty={dirty} remote={audit.get('remote', '')[:60]}"
        )
        if unpushed > 0:
            result = _auto_push(name, root, branch)
            actions.append(result)
            if result.get("ok"):
                print(f"  PUSH OK {name}")
            else:
                msg = f"{name} push failed ({result.get('code')})"
                issues.append(msg)
                print(f"  PUSH FAIL {name}: {result.get('stderr')}")
        elif dirty > 0:
            issues.append(f"{name}: {dirty} dirty files (nothing committed to push)")

    if issues:
        print(f"\n[ISSUES: {len(issues)}]")
        for i in issues:
            print(f"  - {i}")
        return 1

    print("\n[OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())