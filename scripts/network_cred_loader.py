#!/usr/bin/env python3
"""Load network device credentials from Bitwarden-hydrated env vars (no plaintext in repo)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _resolve_ssh_key() -> Optional[str]:
    explicit = _env("NETWORK_ROUTER_SSH_KEY")
    if explicit and Path(explicit).is_file():
        return explicit
    home = Path.home() / ".ssh"
    for name in ("id_ed25519_network", "id_ed25519", "id_rsa"):
        candidate = home / name
        if candidate.is_file():
            return str(candidate)
    return None


def router_ssh_creds() -> Dict[str, Any]:
    host = _env("NETWORK_ROUTER_HOST")
    user = _env("NETWORK_ROUTER_USER")
    password = _env("NETWORK_ROUTER_PASSWORD")
    key_path = _resolve_ssh_key()
    key_ok = bool(key_path and Path(key_path).is_file())
    configured = bool(host and user and (key_ok or password))
    if password:
        auth_mode = "password"
    elif key_ok:
        auth_mode = "ssh_key"
    else:
        auth_mode = "none"
    return {
        "host": host,
        "user": user,
        "password_set": bool(password),
        "ssh_key": key_path,
        "ssh_key_set": key_ok,
        "auth_mode": auth_mode,
        "configured": configured,
    }


def list_credential_status() -> Dict[str, Any]:
    router = router_ssh_creds()
    missing: List[str] = []
    if not router["host"]:
        missing.append("NETWORK_ROUTER_HOST")
    if not router["user"]:
        missing.append("NETWORK_ROUTER_USER")
    if not router["ssh_key_set"] and not router["password_set"]:
        missing.append("NETWORK_ROUTER_SSH_KEY_or_PASSWORD")
    return {
        "source": "bitwarden_env",
        "auth_preferred": "password" if router.get("password_set") else "ssh_key",
        "router_ssh_configured": router["configured"],
        "auth_mode": router.get("auth_mode"),
        "password_set": router.get("password_set"),
        "ssh_key_path": router.get("ssh_key"),
        "missing_env": missing,
    }


def main() -> int:
    import json

    try:
        from phronesis_env import bootstrap_env

        bootstrap_env()
    except Exception:
        pass

    print(json.dumps(list_credential_status()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())