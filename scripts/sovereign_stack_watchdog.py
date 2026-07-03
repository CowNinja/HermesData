#!/usr/bin/env python3
"""
sovereign_stack_watchdog.py — 60s stack nervous system (lightweight).

Complements model_management_agent.py (heavy inventory/ranking cron).
This watchdog: port matrix, bounded MoE+proxy recovery, telemetry optimize,
memory hydrate, operations feed refresh.

Usage:
  python sovereign_stack_watchdog.py --once
  python sovereign_stack_watchdog.py --interval 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPTS = Path(__file__).resolve().parent
VAULT = Path(r"D:\PhronesisVault")
WATCHDOG_STATE = VAULT / "Operations" / "logs" / "sovereign-watchdog-state.json"
WATCHDOG_LOG = VAULT / "Operations" / "logs" / "sovereign-stack-watchdog.jsonl"

# Model management agent runs on slower cadence (dashboard refresh / cron)
MGMT_AGENT = SCRIPTS / "model_management_agent.py"
MGMT_INTERVAL_SEC = 3600


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: Dict[str, Any]) -> None:
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _load_state() -> Dict[str, Any]:
    if WATCHDOG_STATE.is_file():
        try:
            return json.loads(WATCHDOG_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ticks": 0, "last_mgmt_tick": 0.0}


def _save_state(state: Dict[str, Any]) -> None:
    WATCHDOG_STATE.parent.mkdir(parents=True, exist_ok=True)
    WATCHDOG_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def memory_hydrate_tick() -> Dict[str, Any]:
    """Boot-hydrate sovereign memory for gateway continuity."""
    try:
        from sovereign_memory_manager import hydrate_boot_state  # type: ignore

        payload = hydrate_boot_state(platform="hermes")
        return {"ok": True, "event": "memory_hydrate", "hydrated": bool(payload)}
    except Exception as exc:
        return {"ok": False, "event": "memory_hydrate", "error": str(exc)}


def run_tick(*, auto_recover: bool = True, run_mgmt: bool = False, once: bool = False) -> Dict[str, Any]:
    """Single watchdog cycle."""
    sys.path.insert(0, str(SCRIPTS))
    from model_resource_manager import preflight_for_agent, tier_matrix, append_watchdog_log  # type: ignore
    from sovereign_telemetry_monitor import get_telemetry_monitor  # type: ignore
    from autonomous_operations_feed import refresh_panel  # type: ignore

    state = _load_state()
    state["ticks"] = int(state.get("ticks") or 0) + 1

    preflight = preflight_for_agent(auto_recover=auto_recover)
    matrix = preflight.get("matrix") or tier_matrix(force_refresh=True)
    telemetry_optimize = get_telemetry_monitor().optimize_tick()
    hydrate = memory_hydrate_tick()
    ops_feed = refresh_panel()

    mgmt_result: Optional[Dict[str, Any]] = None
    now = time.time()
    last_mgmt = float(state.get("last_mgmt_tick") or 0.0)
    should_mgmt = run_mgmt or (not once and (now - last_mgmt) >= MGMT_INTERVAL_SEC)
    if should_mgmt:
        try:
            import subprocess

            py = SCRIPTS.parent / "hermes-agent" / "venv" / "Scripts" / "python.exe"
            if not py.is_file():
                py = Path(sys.executable)
            proc = subprocess.run(
                [str(py), str(MGMT_AGENT), "--tick"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(SCRIPTS),
            )
            parsed: Dict[str, Any] = {}
            if proc.stdout.strip():
                try:
                    parsed = json.loads(proc.stdout)
                except Exception:
                    parsed = {"raw": proc.stdout[-600:]}
            mgmt_result = {"ok": proc.returncode == 0, **parsed}
            state["last_mgmt_tick"] = now
        except Exception as exc:
            mgmt_result = {"ok": False, "error": str(exc)}

    tick_payload = {
        "event": "watchdog_tick",
        "tick_number": state["ticks"],
        "preflight": {
            "ok": preflight.get("ok"),
            "recovered": preflight.get("recovered"),
            "recoveries": preflight.get("recoveries"),
        },
        "telemetry_optimize": telemetry_optimize,
        "memory_hydrate": hydrate,
        "operations_feed": {"ok": True, "status": ops_feed.get("status")},
        "model_management": mgmt_result,
    }

    append_watchdog_log(tick_payload)
    _log(tick_payload)

    state["last_status"] = matrix.get("status")
    state["last_tick_at"] = _utc_now()
    state["last_matrix"] = matrix
    _save_state(state)

    return {"tick": tick_payload, "matrix": matrix, "operations_panel": ops_feed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sovereign stack watchdog")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit")
    parser.add_argument("--interval", type=int, default=60, help="Daemon interval seconds")
    parser.add_argument("--no-recover", action="store_true", help="Probe only, no auto-recover")
    parser.add_argument("--with-mgmt", action="store_true", help="Force model_management_agent tick")
    args = parser.parse_args()

    auto_recover = not args.no_recover

    if args.once:
        result = run_tick(auto_recover=auto_recover, run_mgmt=args.with_mgmt, once=True)
        print(json.dumps(result, indent=2))
        status = (result.get("matrix") or {}).get("status")
        return 0 if status in ("GREEN", "YELLOW") else 1

    while True:
        try:
            run_tick(auto_recover=auto_recover, run_mgmt=args.with_mgmt, once=False)
        except Exception as exc:
            _log({"event": "watchdog_error", "error": str(exc)})
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())