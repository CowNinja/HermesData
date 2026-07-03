#!/usr/bin/env python3
"""Push canonical .env secrets into Bitwarden Secrets Manager project.

Never prints secret values. BWS_ACCESS_TOKEN stays local-only (bootstrap).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

HERMES_ROOT = Path(r"D:\HermesData")
CANONICAL = HERMES_ROOT / ".env"
CONFIG = HERMES_ROOT / "config.yaml"
BWS = HERMES_ROOT / "bin" / "bws.exe"
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

# Bootstrap token must remain in .env only (Hermes design).
NEVER_PUSH = frozenset({"BWS_ACCESS_TOKEN"})

# Skip paths, ports, debug toggles, non-secret config.
SKIP_SUFFIXES = ("_DEBUG", "_PATH", "_URL", "_ENABLED", "_MODE", "_TIMEOUT")
SKIP_EXACT = frozenset({
    "PORT", "HOST", "COOKIE_SECURE", "HERMES_TRUST_LOCALHOST", "LOG_LEVEL",
    "SANDBOX_MODE", "GITHUB_REPO", "OLLAMA_HOST", "OLLAMA_MODEL", "VM_IP",
    "VM_USER", "API_SERVER_ENABLED", "HERMES_AGENT_PATH", "HERMES_CLI_BIN",
    "HERMES_DASHBOARD_URL", "HERMES_API_URL", "VITE_PLAYGROUND_STATS_URL",
    "VITE_PLAYGROUND_WS_URL", "XAI_SEARCH_ENDPOINT", "CHROMA_DB_PATH",
    "SQLITE_DB_PATH", "OBSIDIAN_VAULT_PATH", "TERMINAL_LIFETIME_SECONDS",
    "TERMINAL_MODAL_IMAGE", "BROWSER_INACTIVITY_TIMEOUT", "BROWSER_SESSION_TIMEOUT",
    "BROWSERBASE_ADVANCED_STEALTH", "BROWSERBASE_PROXIES", "DISCORD_ALLOWED_USERS",
    "DISCORD_FREE_RESPONSE_CHANNELS", "DISCORD_HOME_CHANNEL",
    "WHATSAPP_ALLOWED_USERS", "WHATSAPP_HOME_CHANNEL", "WHATSAPP_HOME_CHANNEL_THREAD_ID",
    "REPLIKA_CHAT_ID", "REPLIKA_DEVICE_ID", "REPLIKA_USER_ID", "DUCKDUCKGO_API",
})


def _should_push(key: str) -> bool:
    if key in NEVER_PUSH or key in SKIP_EXACT:
        return False
    if any(key.endswith(s) for s in SKIP_SUFFIXES):
        return False
    if key.endswith("_API_KEY") or key.endswith("_TOKEN") or key.endswith("_AUTHTOKEN"):
        return True
    if key.endswith(("_PASSWORD", "_PASSPHRASE", "_SECRET", "_SID")):
        return True
    if key in ("HERMES_PASSWORD", "VM_PASSWORD", "API_SERVER_KEY", "TWILIO_PHONE_NUMBER"):
        return True
    return False


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = KEY_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _project_id() -> str:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    pid = str((cfg.get("secrets") or {}).get("bitwarden", {}).get("project_id", "")).strip()
    if not pid:
        raise SystemExit("config.yaml secrets.bitwarden.project_id is empty")
    return pid


def _write_import_json(project_id: str, to_push: dict[str, str]) -> Path:
    out = HERMES_ROOT / "secrets" / "bitwarden-hermes-import.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    secrets = []
    for i, (key, value) in enumerate(sorted(to_push.items()), 1):
        secrets.append({
            "key": key,
            "value": value,
            "note": "Imported from D:\\HermesData\\.env by populate_bitwarden_project.py",
            "id": f"00000000-0000-0000-0000-{i:012d}",
            "projectIds": [project_id],
        })
    payload = {"projects": [], "secrets": secrets}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> int:
    sys.path.insert(0, str(HERMES_ROOT / "scripts"))
    import phronesis_env

    phronesis_env.bootstrap_env()

    if not BWS.exists():
        raise SystemExit(f"bws missing: {BWS}")

    project_id = _project_id()
    env = _parse_env(CANONICAL)
    to_push = {k: v for k, v in env.items() if v and _should_push(k)}

    created: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    need_write = False

    for key in sorted(to_push):
        r = subprocess.run(
            [str(BWS), "secret", "create", key, to_push[key], project_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            created.append(key)
        else:
            err = (r.stderr or r.stdout or "").strip()
            if "already exists" in err.lower() or "duplicate" in err.lower():
                skipped.append(key)
            elif "404" in err or "not found" in err.lower():
                need_write = True
                errors.append(f"{key}: machine account lacks write permission")
            else:
                errors.append(f"{key}: {(err.splitlines() or ['unknown'])[0][:120]}")

    import_path = None
    if need_write and not created:
        import_path = _write_import_json(project_id, to_push)

    report = {
        "project_id": project_id,
        "keys_targeted": len(to_push),
        "key_names": sorted(to_push),
        "created": len(created),
        "created_keys": created,
        "skipped_existing": skipped,
        "errors": errors,
        "import_file": str(import_path) if import_path else None,
        "import_hint": (
            "Secrets Manager → Settings → Import data → choose import file "
            "(or grant machine account Can read, write on project and re-run)"
            if import_path
            else None
        ),
    }
    print(json.dumps(report, indent=2))
    return 0 if created or import_path else 1


if __name__ == "__main__":
    raise SystemExit(main())