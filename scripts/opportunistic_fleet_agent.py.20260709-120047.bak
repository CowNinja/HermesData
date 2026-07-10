#!/usr/bin/env python3
"""
opportunistic_fleet_agent.py — Autonomous Opportunistic Fleet Procurement Curator.

Delegates to fleet_procurement_engine for discover → sandbox → benchmark → promote/disable.
Provider-agnostic: routing uses capability tags only.

Usage:
  python opportunistic_fleet_agent.py --procure-tick
  python opportunistic_fleet_agent.py --simulate-loop
  python opportunistic_fleet_agent.py --health-cycle
  python opportunistic_fleet_agent.py --discover-only
  python opportunistic_fleet_agent.py --full-tick
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

HERMES_SCRIPTS = Path(__file__).resolve().parent
CURATOR_REPORT = Path(r"D:\PhronesisVault\Operations\logs\fleet-curator-report.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _engine():
    sys.path.insert(0, str(HERMES_SCRIPTS))
    from fleet_procurement_engine import FleetProcurementEngine

    return FleetProcurementEngine()


def procure_tick(*, discover: bool = True, force: bool = False) -> Dict[str, Any]:
    """Autonomous procurement tick: re-validate production + discover/sandbox/promote."""
    engine = _engine()
    if force:
        state = engine.governor.load_state()
        state["last_tick"] = None
        engine.governor.save_state(state)
    report = engine.procure_tick(discover=discover)
    _write_report({"mode": "procure_tick", **report})
    return report


def simulate_loop() -> Dict[str, Any]:
    """Simulated discovery→sandbox→benchmark→promote without registry pollution."""
    report = _engine().simulate_loop()
    _write_report(report)
    return report


def discover_only() -> Dict[str, Any]:
    """Discovery phase only (no sandbox inject)."""
    candidates = _engine().discover_candidates()
    report = {"timestamp": _utc_now(), "mode": "discover_only", "count": len(candidates), "candidates": candidates}
    _write_report(report)
    return report


def health_cycle() -> Dict[str, Any]:
    """Lightweight health cycle on routable production providers."""
    sys.path.insert(0, str(HERMES_SCRIPTS))
    from external_fleet_manager import FleetManager

    result = FleetManager().run_health_cycle()
    _write_report({"mode": "health_cycle", "timestamp": _utc_now(), **result})
    return result


def auto_disable_unhealthy(*, max_failures: int = 3) -> Dict[str, Any]:
    """Disable providers that fail health checks repeatedly."""
    sys.path.insert(0, str(HERMES_SCRIPTS))
    from external_fleet_manager import FleetManager, HEALTH_STATE

    fm = FleetManager()
    engine = _engine()
    health = json.loads(HEALTH_STATE.read_text(encoding="utf-8")) if HEALTH_STATE.is_file() else {}
    providers_health = health.get("providers") or {}
    disabled = []

    for section in ("compute_providers", "context_providers"):
        for p in fm._registry.get(section) or []:
            pid = str(p.get("id") or "")
            h = providers_health.get(pid) or {}
            if h.get("status") == "down" and p.get("enabled"):
                fails = int(h.get("consecutive_failures") or 0) + 1
                h["consecutive_failures"] = fails
                if fails >= max_failures:
                    engine.disable_provider(pid, f"health_failures_{fails}")
                    disabled.append(pid)

    return {"disabled": disabled, "checked": len(providers_health)}


def optimize_tick() -> Dict[str, Any]:
    """Telemetry auto-triage + zombie scan + governor auto-tune."""
    sys.path.insert(0, str(HERMES_SCRIPTS))
    from sovereign_telemetry_monitor import get_telemetry_monitor

    report = get_telemetry_monitor().optimize_tick()
    _write_report({"mode": "optimize_tick", "timestamp": _utc_now(), **report})
    return report


def full_tick(*, discover: bool = True, force: bool = False) -> Dict[str, Any]:
    """Cron entry: procurement tick (primary) + health summary."""
    report: Dict[str, Any] = {"timestamp": _utc_now(), "mode": "full_tick"}
    report["procurement"] = procure_tick(discover=discover, force=force)
    report["health"] = health_cycle()
    report["auto_fix"] = auto_disable_unhealthy()
    report["telemetry"] = optimize_tick()
    report["status"] = "complete"
    _write_report(report)
    return report


def _write_report(report: Dict[str, Any]) -> None:
    try:
        CURATOR_REPORT.parent.mkdir(parents=True, exist_ok=True)
        CURATOR_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Opportunistic Fleet Procurement Curator")
    parser.add_argument("--procure-tick", action="store_true", help="Autonomous procurement tick")
    parser.add_argument("--simulate-loop", action="store_true", help="Simulated discover→promote loop")
    parser.add_argument("--discover-only", action="store_true", help="Discovery candidates only")
    parser.add_argument("--health-cycle", action="store_true", help="Production health cycle")
    parser.add_argument("--full-tick", action="store_true", help="Procurement + health (cron)")
    parser.add_argument("--auto-fix", action="store_true", help="Auto-disable unhealthy providers")
    parser.add_argument("--optimize-tick", action="store_true", help="Telemetry auto-triage + zombie scan")
    parser.add_argument("--force", action="store_true", help="Bypass procurement cooldown")
    args = parser.parse_args()

    if args.simulate_loop:
        out = simulate_loop()
    elif args.optimize_tick:
        out = optimize_tick()
    elif args.procure_tick:
        out = procure_tick(force=args.force)
    elif args.discover_only:
        out = discover_only()
    elif args.full_tick:
        out = full_tick(force=args.force)
    elif args.auto_fix:
        out = auto_disable_unhealthy()
    elif args.health_cycle:
        out = health_cycle()
    else:
        sys.path.insert(0, str(HERMES_SCRIPTS))
        from external_fleet_manager import FleetManager

        out = FleetManager().status()

    print(json.dumps(out, indent=2))
