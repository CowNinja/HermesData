#!/usr/bin/env python3
"""Local Git backup for network configs -- replaces Oxidized for homelab scale."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SCRIPTS = Path(__file__).resolve().parent
import sys

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adapters.network.ssh_backup import SshBackupAdapter, BACKUP_DIR  # noqa: E402

GIT_REPO = BACKUP_DIR
NETWORK_TOOLS = Path(r"D:\HermesData\config\network_tools.yaml")


def _ssh_backup_enabled() -> tuple[bool, str]:
    try:
        import yaml  # type: ignore

        if not NETWORK_TOOLS.is_file():
            return True, ""
        data = yaml.safe_load(NETWORK_TOOLS.read_text(encoding="utf-8")) or {}
        backup = data.get("backup") or {}
        if backup.get("ssh_enabled") is False:
            return False, str(backup.get("ssh_skip_reason") or "ssh_disabled_in_yaml")
    except Exception:
        pass
    return True, ""


def _git(args: List[str], cwd: Path) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": (result.stdout or "").strip()[:500],
            "stderr": (result.stderr or "").strip()[:500],
        }
    except FileNotFoundError:
        return {"ok": False, "error": "git_not_on_path"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ensure_repo() -> Dict[str, Any]:
    GIT_REPO.mkdir(parents=True, exist_ok=True)
    if not (GIT_REPO / ".git").is_dir():
        init = _git(["init"], GIT_REPO)
        if not init.get("ok"):
            return init
        _git(["config", "user.email", "hermes@phronesis.local"], GIT_REPO)
        _git(["config", "user.name", "Hermes Network Backup"], GIT_REPO)
    return {"ok": True, "repo": str(GIT_REPO)}


def commit_backups(message: str) -> Dict[str, Any]:
    repo_ok = ensure_repo()
    if not repo_ok.get("ok"):
        return repo_ok
    _git(["add", "-A"], GIT_REPO)
    status = _git(["status", "--porcelain"], GIT_REPO)
    if not status.get("stdout"):
        return {"ok": True, "committed": False, "reason": "no_changes"}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = _git(["commit", "-m", f"{message} {ts}"], GIT_REPO)
    return {"ok": commit.get("ok"), "committed": commit.get("ok"), "repo": str(GIT_REPO)}


def run_backup_flow() -> Dict[str, Any]:
    enabled, reason = _ssh_backup_enabled()
    if not enabled:
        return {
            "ok": True,
            "skipped": True,
            "reason": "ssh_disabled_in_registry",
            "hint": reason,
        }
    adapter = SshBackupAdapter()
    if not adapter.is_configured():
        return {
            "ok": False,
            "skipped": True,
            "reason": "ssh_not_configured",
            "hint": "Set NETWORK_ROUTER_HOST, USER, SSH_KEY in Bitwarden; restart gateway",
        }
    backup = adapter.backup_config_readonly()
    if not backup.get("ok"):
        return backup
    git_result = commit_backups("network config backup")
    return {"ok": True, "backup": backup, "git": git_result}


def main() -> int:
    try:
        from phronesis_env import bootstrap_env

        bootstrap_env()
    except Exception:
        pass
    result = run_backup_flow()
    print(json.dumps(result))
    if result.get("skipped"):
        return 0
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())