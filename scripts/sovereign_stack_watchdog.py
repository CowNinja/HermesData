#!/usr/bin/env python3
"""
sovereign_stack_watchdog.py — 60s MoE + proxy self-heal tick.

Runs model_resource_manager.preflight_for_agent(auto_recover=True) with bounded
retries. Each tick also runs telemetry --optimize-tick (zombie scan + auto-triage)
and refreshes the autonomous operations dashboard feed.

Logs to sovereign-stack-watchdog.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(HERMES_SCRIPTS))

DEFAULT_INTERVAL_SEC = 60
STATE_PATH = Path(r"D:\PhronesisVault\Operations\logs\sovereign-watchdog-state.json")
WATCHDOG_LOG = Path(r"D:\PhronesisVault\Operations\logs\sovereign-stack-watchdog.jsonl")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(event: dict) -> None:
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _load_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ticks": 0, "last_status": None}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _run_telemetry_optimize() -> dict:
    try:
        from sovereign_telemetry_monitor import get_telemetry_monitor
        return get_telemetry_monitor().optimize_tick()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _refresh_operations_feed() -> dict:
    try:
        from autonomous_operations_feed import refresh_panel
        return {"ok": True, "status": refresh_panel().get("status")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_tick(auto_recover: bool = True) -> dict:
    from model_resource_manager import append_watchdog_log, preflight_for_agent, tier_matrix

    memory_boot = None
    try:
        from sovereign_memory_manager import hydrate_boot_state

        memory_boot = hydrate_boot_state(platform="sovereign_watchdog")
    except Exception:
        pass

    matrix_before = tier_matrix()
    result = preflight_for_agent(auto_recover=auto_recover)
    matrix_after = result.get("matrix") or tier_matrix()

    telemetry = _run_telemetry_optimize()
    ops_feed = _refresh_operations_feed()

    tick = {
        "event": "watchdog_tick",
        "status_before": matrix_before.get("status"),
        "status_after": matrix_after.get("status"),
        "agent_local_ready": matrix_after.get("agent_local_ready"),
        "moe_ready": matrix_after.get("moe_ready"),
        "proxy_ready": matrix_after.get("proxy_ready"),
        "recovered": result.get("recovered", False),
        "recoveries": result.get("recoveries", []),
        "cooldown_reset": result.get("cooldown_reset"),
        "telemetry_optimize": {
            "zombie_events": len(telemetry.get("zombie_events") or []),
            "governor_stress": telemetry.get("governor_stress"),
            "combined_stress": (telemetry.get("providers") or {}) and telemetry.get("governor_stress"),
        },
        "operations_feed": ops_feed,
        "memory_hydrate": {
            "session_id": (memory_boot or {}).get("session_id"),
            "hydrated": (memory_boot or {}).get("hydrated"),
        } if memory_boot else None,
    }
    try:
        from sovereign_telemetry_monitor import get_telemetry_monitor
        tstatus = get_telemetry_monitor().status()
        tick["telemetry_optimize"]["combined_stress"] = tstatus.get("combined_stress")
        tick["telemetry_optimize"]["procurement_deferred"] = tstatus.get("procurement_deferred")
        tick["telemetry_optimize"]["governor_stress"] = tstatus.get("governor_stress")
    except Exception:
        pass

    append_watchdog_log(tick)
    _append_log(tick)

    state = _load_state()
    state["ticks"] = int(state.get("ticks", 0)) + 1
    state["last_tick"] = _utc_now()
    state["last_status"] = matrix_after.get("status")
    state["last_agent_ready"] = matrix_after.get("agent_local_ready")
    state["last_telemetry"] = tick.get("telemetry_optimize")
    _save_state(state)

    return {"tick": tick, "state": state, "matrix": matrix_after}


def run_daemon(interval_sec: int = DEFAULT_INTERVAL_SEC, auto_recover: bool = True) -> int:
    _append_log({"event": "watchdog_daemon_start", "interval_sec": interval_sec})
    try:
        while True:
            report = run_tick(auto_recover=auto_recover)
            status = report["tick"]["status_after"]
            ready = report["tick"]["agent_local_ready"]
            _append_log({
                "event": "watchdog_daemon_heartbeat",
                "status": status,
                "agent_ready": ready,
                "recovered": report["tick"]["recovered"],
            })
            time.sleep(max(5, interval_sec))
    except KeyboardInterrupt:
        _append_log({"event": "watchdog_daemon_stop"})
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sovereign MoE + proxy watchdog")
    parser.add_argument("--once", action="store_true", help="Single tick then exit")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC, help="Daemon tick interval (seconds)")
    parser.add_argument("--no-recover", action="store_true", help="Probe only; do not attempt recovery")
    args = parser.parse_args()

    if args.once:
        print(json.dumps(run_tick(auto_recover=not args.no_recover), indent=2))
        return 0

    return run_daemon(interval_sec=args.interval, auto_recover=not args.no_recover)


if __name__ == "__main__":
    raise SystemExit(main())
