#!/usr/bin/env python3
"""SSH read-only backup -- OpenSSH native on Windows 11, Git local history."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from adapters.network.base import NetworkAdapter

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from network_cred_loader import router_ssh_creds  # noqa: E402

BACKUP_DIR = Path(r"D:\PhronesisVault\Operations\network-backups")

# Read-only commands per vendor hint (inventory Admin API field)
_VENDOR_CMD = {
    "openwrt": "uci show",
    "asus": "nvram show | head -100",
    "unifi": "info",
    "portal": "show version",
    "generic": "show version",
}

_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ConnectTimeout=10",
    # Portal SAP102 ships legacy OpenSSH (group14-sha1 only).
    "-o",
    "KexAlgorithms=+diffie-hellman-group14-sha1",
    "-o",
    "HostKeyAlgorithms=+ssh-rsa",
    "-o",
    "PubkeyAcceptedAlgorithms=+ssh-rsa",
]


def _bootstrap() -> None:
    try:
        from phronesis_env import bootstrap_env

        bootstrap_env()
    except Exception:
        pass


def _remote_command(vendor: str = "generic") -> str:
    key = vendor.strip().lower()
    for token, cmd in _VENDOR_CMD.items():
        if token in key:
            return cmd
    return _VENDOR_CMD["generic"]


def _write_askpass_helper() -> tuple[Path, Path]:
    """Windows OpenSSH needs a .cmd launcher; helper reads password from env only."""
    fd, py_name = tempfile.mkstemp(suffix="_ssh_askpass.py", text=True)
    os.close(fd)
    py_helper = Path(py_name)
    py_helper.write_text(
        "import os, sys\n"
        "sys.stdout.write(os.environ.get('NETWORK_ROUTER_PASSWORD', ''))\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    cmd_path = py_helper.with_suffix(".cmd")
    cmd_path.write_text(
        f'@"{sys.executable}" "{py_helper}"\n',
        encoding="ascii",
    )
    return cmd_path, py_helper


def _run_openssh(
    host: str,
    user: str,
    remote_cmd: str,
    *,
    key_path: str | None = None,
    password: str | None = None,
) -> subprocess.CompletedProcess[str]:
    ssh_args = ["ssh", *_SSH_OPTS]
    env = os.environ.copy()

    askpass_cmd: Path | None = None
    askpass_py: Path | None = None
    if password:
        askpass_cmd, askpass_py = _write_askpass_helper()
        env["NETWORK_ROUTER_PASSWORD"] = password
        env["SSH_ASKPASS"] = str(askpass_cmd)
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", "1")
        ssh_args.extend(["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"])
    elif key_path:
        ssh_args.extend(["-i", str(key_path), "-o", "BatchMode=yes"])
    else:
        ssh_args.extend(["-o", "BatchMode=yes"])

    ssh_args.append(f"{user}@{host}")
    ssh_args.append(remote_cmd)

    try:
        return subprocess.run(
            ssh_args,
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
    finally:
        if password and askpass_cmd:
            try:
                askpass_cmd.unlink(missing_ok=True)
                if askpass_py and askpass_py.is_file():
                    askpass_py.unlink(missing_ok=True)
            except Exception:
                pass


class SshBackupAdapter(NetworkAdapter):
    name = "ssh_backup"

    def is_configured(self) -> bool:
        _bootstrap()
        return bool(router_ssh_creds().get("configured"))

    def read_inventory(self) -> Dict[str, Any]:
        _bootstrap()
        creds = router_ssh_creds()
        return {
            "adapter": self.name,
            "configured": creds.get("configured"),
            "host": creds.get("host") or None,
            "user": creds.get("user") or None,
            "auth_mode": creds.get("auth_mode"),
            "backup_dir": str(BACKUP_DIR),
        }

    def backup_config_readonly(self, vendor: str = "portal") -> Dict[str, Any]:
        _bootstrap()
        creds = router_ssh_creds()
        if not creds.get("configured"):
            return {"ok": False, "error": "ssh_creds_not_configured"}

        host = str(creds.get("host"))
        user = str(creds.get("user"))
        remote_cmd = _remote_command(vendor)
        password = (os.environ.get("NETWORK_ROUTER_PASSWORD") or "").strip()
        key_path = creds.get("ssh_key") if creds.get("auth_mode") == "ssh_key" else None

        if creds.get("auth_mode") == "password" and not password:
            return {
                "ok": False,
                "error": "password_auth_selected_but_NETWORK_ROUTER_PASSWORD_missing",
            }

        try:
            result = _run_openssh(
                host,
                user,
                remote_cmd,
                key_path=str(key_path) if key_path else None,
                password=password if creds.get("auth_mode") == "password" else None,
            )
            text = (result.stdout or "") + (result.stderr or "")
            text = text[:8000]
            if result.returncode != 0:
                err = text[:500] or "ssh_failed"
                hint = "Check NETWORK_ROUTER_PASSWORD in Secrets Manager (Portal SSH != web GUI)."
                if "Permission denied" in text:
                    hint = (
                        "Portal rejected SSH password. Confirm SSH password in Secrets Manager "
                        "(may differ from myportalwifi.com web login)."
                    )
                return {"ok": False, "error": err, "hint": hint}
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_host = host.replace(".", "_")
            out_path = BACKUP_DIR / f"{safe_host}_{ts}.txt"
            out_path.write_text(text, encoding="utf-8")
            latest = BACKUP_DIR / f"{safe_host}_latest.txt"
            latest.write_text(text, encoding="utf-8")
            return {
                "ok": True,
                "path": str(out_path),
                "latest": str(latest),
                "bytes": len(text),
                "command": remote_cmd,
                "auth_mode": creds.get("auth_mode"),
            }
        except FileNotFoundError:
            return {"ok": False, "error": "ssh_client_not_found"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def recommend(self, audit: Dict[str, Any]) -> List[str]:
        recs: List[str] = []
        if not self.is_configured():
            recs.append("add_network_router_creds_bitwarden_or_ssh_key")
        else:
            recs.append("run_network_backup_git_for_history")
        return recs