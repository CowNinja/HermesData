#!/usr/bin/env python3
"""Ensure XAI_API_KEY exists in Bitwarden Secrets Manager (one-time migration helper)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\HermesData")
BWS = ROOT / "bin" / "bws.exe"
CONFIG = ROOT / "config.yaml"
LEGACY_SOURCES = (
    ROOT / "secrets" / "infisical-export-prod.env",
    ROOT / "secrets" / "infisical-export-dev.env",
    ROOT / ".env",
)


def _clean(val: str) -> str:
    s = str(val or "").strip().strip("'\"")
    if " #" in s:
        s = s.split(" #", 1)[0].rstrip()
    return s


def _project_id() -> str:
    import yaml

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return str((cfg.get("secrets") or {}).get("bitwarden", {}).get("project_id", "")).strip()


def _find_xai_key() -> str:
    for path in LEGACY_SOURCES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("XAI_API_KEY="):
                val = _clean(line.split("=", 1)[1])
                if val.startswith("xai-"):
                    return val
            m = re.match(r"^grok AI API='?(.+?)'?\s*$", line.strip(), re.I)
            if m:
                val = _clean(m.group(1))
                if val.startswith("xai-"):
                    return val
    return ""


def _bws(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BWS), *args],
        capture_output=True,
        text=True,
        timeout=45,
    )


def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from phronesis_env import bootstrap_env

    bootstrap_env()
    if not BWS.is_file():
        print(json.dumps({"ok": False, "error": "bws_missing", "path": str(BWS)}))
        return 1

    project_id = _project_id()
    if not project_id:
        print(json.dumps({"ok": False, "error": "project_id_missing"}))
        return 1

    key_val = _find_xai_key()
    if not key_val:
        print(json.dumps({"ok": False, "error": "xai_key_not_found_locally"}))
        return 1

    listed = _bws(["secret", "list", project_id])
    existing: set[str] = set()
    if listed.returncode == 0:
        try:
            existing = {s.get("key") for s in json.loads(listed.stdout) if s.get("key")}
        except json.JSONDecodeError:
            pass

    secret_id = ""
    if listed.returncode == 0:
        try:
            for row in json.loads(listed.stdout):
                if row.get("key") == "XAI_API_KEY":
                    secret_id = str(row.get("id") or "")
                    break
        except json.JSONDecodeError:
            pass

    if not secret_id:
        created = _bws(["secret", "create", "XAI_API_KEY", key_val, project_id])
        if created.returncode != 0:
            err = (created.stderr or created.stdout or "").strip()[:200]
            print(json.dumps({"ok": False, "error": "create_failed", "detail": err}))
            return 1
        action = "created"
    else:
        edited = _bws(["secret", "edit", secret_id, "--value", key_val])
        if edited.returncode != 0:
            err = (edited.stderr or edited.stdout or "").strip()[:200]
            print(json.dumps({"ok": False, "error": "edit_failed", "detail": err}))
            return 1
        action = "updated"

    cache = ROOT / "cache" / "bws_cache.json"
    if cache.is_file():
        try:
            cache.unlink()
        except OSError:
            pass

    print(json.dumps({"ok": True, "action": action, "key": "XAI_API_KEY", "project_id": project_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())