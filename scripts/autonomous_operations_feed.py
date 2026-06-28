#!/usr/bin/env python3
"""
autonomous_operations_feed.py — Dashboard feed for System Health / Autonomous Operations.

Tails system_optimizations.jsonl + telemetry state into a JSON panel for :3001 dashboard.

Usage:
  python autonomous_operations_feed.py --refresh
  python autonomous_operations_feed.py --stdout
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

OPTIMIZATION_LOG = Path(r"D:\PhronesisVault\Operations\logs\system_optimizations.jsonl")
TELEMETRY_STATE = Path(r"D:\PhronesisVault\Operations\logs\sovereign-telemetry-state.json")
TELEMETRY_REPORT = Path(r"D:\PhronesisVault\Operations\logs\sovereign-telemetry-report.json")
WATCHDOG_STATE = Path(r"D:\PhronesisVault\Operations\logs\sovereign-watchdog-state.json")
PANEL_OUT = Path(r"D:\PhronesisVault\Operations\autonomous-operations-panel.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl_tail(path: Path, limit: int = 40) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _format_entry(evt: Dict[str, Any]) -> str:
    msg = str(evt.get("message") or "").strip()
    if msg:
        return msg
    action = str(evt.get("action") or "event")
    pid = evt.get("provider_id") or evt.get("pid") or ""
    return f"{action} {pid}".strip()


def build_panel(*, tail_limit: int = 30) -> Dict[str, Any]:
    events = _read_jsonl_tail(OPTIMIZATION_LOG, tail_limit)
    telemetry_state = _load_json(TELEMETRY_STATE)
    telemetry_report = _load_json(TELEMETRY_REPORT)
    watchdog = _load_json(WATCHDOG_STATE)

    blacklisted = [
        pid for pid, pdata in (telemetry_state.get("providers") or {}).items()
        if pdata.get("blacklisted_until")
    ]
    recent_actions = events[-12:]
    action_counts: Dict[str, int] = {}
    for e in events:
        act = str(e.get("action") or "unknown")
        action_counts[act] = action_counts.get(act, 0) + 1

    combined_stress = int(telemetry_state.get("combined_stress_level") or 0)
    local_stress = int(telemetry_state.get("local_stress_level") or 0)
    gov_stress = int(telemetry_state.get("governor_stress_level") or 0)
    defer = combined_stress >= 2

    status = "GREEN"
    if combined_stress >= 4 or action_counts.get("zombie_terminated", 0) > 2:
        status = "RED"
    elif combined_stress >= 2 or blacklisted:
        status = "YELLOW"

    lines = [_format_entry(e) for e in reversed(recent_actions)]

    return {
        "panel_type": "autonomous_operations",
        "version": "1.0",
        "updated_at": _utc_now(),
        "status": status,
        "summary": {
            "combined_stress": combined_stress,
            "local_stress": local_stress,
            "governor_stress": gov_stress,
            "procurement_deferred": defer,
            "blacklisted_providers": blacklisted,
            "watchdog_ticks": watchdog.get("ticks"),
            "watchdog_last_status": watchdog.get("last_status"),
            "active_zombie_tasks": len(telemetry_report.get("active_tasks") or []),
        },
        "action_counts": action_counts,
        "recent_actions": recent_actions,
        "display_lines": lines,
        "headline": lines[0] if lines else "Autonomous operations nominal",
    }


def refresh_panel() -> Dict[str, Any]:
    panel = build_panel()
    PANEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    PANEL_OUT.write_text(json.dumps(panel, indent=2), encoding="utf-8")
    return panel


if __name__ == "__main__":
    if "--stdout" in sys.argv:
        print(json.dumps(build_panel(), indent=2))
    else:
        print(json.dumps(refresh_panel(), indent=2))
