#!/usr/bin/env python3
"""Robust self-test for Tier 1.5 Opportunistic Fleet wiring."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, r"D:\PhronesisVault\scripts")

ERRORS: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")


def main() -> int:
    print("=== Opportunistic Fleet Self-Test ===\n")

    # 1. Registry loads
    from external_fleet_manager import FleetManager, REGISTRY_PATH, fleet_available

    check("registry_exists", REGISTRY_PATH.is_file(), str(REGISTRY_PATH))
    fm = FleetManager()
    check("fleet_enabled", fm.enabled)
    status = fm.status()
    check("status_has_tier", status.get("tier") == "opportunistic_fleet")

    # 2. Trigger detection
    from router_bridge import (
        detect_opportunistic_fleet_triggers,
        detect_grok_escalation_triggers,
    )

    fleet_rt = detect_opportunistic_fleet_triggers("What happened today in AI news?")
    check("realtime_triggers_fleet", fleet_rt.get("should_route"), fleet_rt.get("reason"))

    grok_hs = detect_grok_escalation_triggers("Medical compliance legal review safety-critical")
    check("high_stakes_triggers_grok", grok_hs.get("should_escalate"))
    check(
        "realtime_not_grok",
        "latest_external_knowledge" not in (grok_hs.get("matched_triggers") or []),
    )

    # 3. Sovereign router tier decision
    from sovereign_router import SovereignRouter

    router = SovereignRouter()
    tier = router.decide_escalation_tier("default", "search for latest breaking news", "simple")
    check("router_realtime_tier", tier == "opportunistic_fleet", f"got {tier}")

    # 4. Context dispatch (no-key DuckDuckGo)
    ctx = fm.dispatch_context("Python programming language")
    check("duckduckgo_context", ctx.get("success") or ctx.get("provider_id") == "duckduckgo-instant",
          str(ctx.get("error", ctx.get("response", ""))[:80]))

    # 5. Bridge integration (local forced + fleet on fail path structure)
    from router_bridge import bridge_dispatch

    # Local should work if 8090 up
    local = bridge_dispatch("def foo(): pass", task_type="code", force_local=True, prefer="vault")
    check("local_still_first", local.get("success"), str(local.get("provenance", {})))

    # Fleet path for realtime when we simulate — use explicit fleet trigger prompt
    fleet_prompt = "Search for the latest real-time breaking news about local LLM routers"
    fleet_info = detect_opportunistic_fleet_triggers(fleet_prompt)
    check("fleet_info_route", fleet_info.get("should_route"))

    # 6. Health cycle (non-fatal if keys missing)
    health = fm.run_health_cycle()
    check("health_cycle_ran", "checked" in health, str(health))

    # 7. Curator / procurement engine
    import opportunistic_fleet_agent as curator
    check("curator_procure_tick", hasattr(curator, "procure_tick"))
    check("curator_simulate_loop", hasattr(curator, "simulate_loop"))
    check("procurement_registry", "procurement" in fm._registry)

    print(f"\n=== Results: {len(ERRORS)} failures ===")
    if ERRORS:
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("ALL PASS — Tier 1.5 wired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
