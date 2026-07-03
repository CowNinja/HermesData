#!/usr/bin/env python3
"""
model_rotation_cron.py — Scheduled model rotation handoff (rotation-lock aware).

When model_rotation_locked is true (current default), logs and exits without swap.
When unlocked, delegates promotion decision to fleetctl suggest and applies via
warm_tier_actions / 02-start-llama.ps1 (Windows-safe — no bash netstat).

Called by Hermes cronjob. Reads lru-router-state.json for workload context.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

HERMES_SCRIPTS = Path(__file__).resolve().parent
VAULT_SCRIPTS = Path(r"D:\PhronesisVault\scripts")
CORE_PATH = HERMES_SCRIPTS / "phronesis-core.json"
STATE_PATH = Path(r"D:\PhronesisVault\Operations\logs\lru-router-state.json")
LOG_PATH = Path(r"D:\PhronesisVault\Operations\logs\model-rotation.jsonl")
WARM_ACTIONS = VAULT_SCRIPTS / "warm_tier_actions.py"
FLEETCTL = VAULT_SCRIPTS / "fleetctl.py"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _run_python(script: Path, args: list[str], timeout: int = 120) -> Dict[str, Any]:
    py = HERMES_SCRIPTS.parent / "hermes-agent" / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
    try:
        proc = subprocess.run(
            [str(py), str(script), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(script.parent),
        )
        out = (proc.stdout or "").strip()
        parsed: Dict[str, Any] = {}
        if out:
            try:
                parsed = json.loads(out)
            except Exception:
                parsed = {"raw": out[-800:]}
        return {"ok": proc.returncode == 0, "returncode": proc.returncode, **parsed}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_loaded_model(port: int = 8090) -> str:
    try:
        import urllib.request

        data = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=3).read()
        )
        models = data.get("data", [])
        if models:
            return str(models[0].get("id", ""))
    except Exception:
        pass
    return ""


def decide_rotation(state: dict, current_model: str, hour: int, suggest: Dict[str, Any]) -> str:
    """Workload heuristics + fleetctl recommendation."""
    rec = suggest.get("recommend") or {}
    if rec.get("action") == "promote" and rec.get("model"):
        target = str(rec["model"])
        if target.lower() not in current_model.lower():
            return target

    last_task = str(state.get("last_task_type") or "")
    tier = str(state.get("last_tier") or "fast")

    if tier == "strong" or last_task in ("code", "reason", "complex", "analysis"):
        for cand in suggest.get("candidates") or []:
            fname = str(cand.get("fname") or "")
            if "14b" in fname.lower() and cand.get("vram_ok"):
                if fname.lower() not in current_model.lower():
                    return fname

    if hour >= 23 or hour < 6:
        for cand in suggest.get("candidates") or []:
            fname = str(cand.get("fname") or "")
            if "q4" in fname.lower() and cand.get("vram_ok"):
                if fname.lower() not in current_model.lower():
                    return fname

    return ""


def apply_rotation(target_file: str) -> Dict[str, Any]:
    """Restart llama with target via unified start script (no manual PID kill)."""
    log_event({"event": "rotation_restart", "target": target_file})
    return _run_python(WARM_ACTIONS, ["start-llama"], timeout=180)


def main() -> int:
    print("=== Model Rotation Cron ===")
    core = _load_json(CORE_PATH)
    if core.get("model_rotation_locked") or core.get("model_locked"):
        msg = "Rotation locked in phronesis-core.json — no swap"
        print(f"  {msg}")
        log_event({"event": "rotation_blocked", "reason": "lock"})
        return 0

    state = _load_json(STATE_PATH)
    current = get_loaded_model()
    hour = datetime.now().hour
    suggest = _run_python(FLEETCTL, ["suggest", "--json"], timeout=90)

    print(f"  Current model: {current or '(unknown)'}")
    print(f"  Hour: {hour}")
    print(f"  Last task: {state.get('last_task_type', 'none')}")

    target = decide_rotation(state, current, hour, suggest)
    if not target:
        print("  No rotation needed.")
        log_event({"event": "no_rotation", "current": current})
        return 0

    print(f"  → Rotating toward: {target}")
    log_event({"event": "rotation_triggered", "from": current, "to": target})
    result = apply_rotation(target)
    if result.get("ok"):
        print("  Rotation restart issued (verify :8090 match in panel)")
        return 0
    print(f"  Rotation restart failed: {result}")
    log_event({"event": "rotation_failed", "target": target, "result": result})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())