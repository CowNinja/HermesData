#!/usr/bin/env python3
"""E2E smoke for T2 opportunistic fleet via sovereign proxy."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(r"D:\PhronesisVault\scripts")))

ERRORS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} -- {detail}")


def main() -> int:
    print("=== T2 Escalation E2E ===\n")

    from escalation_router import fleet_policy, fleet_routing_enabled, try_t2_fleet_dispatch
    from external_fleet_manager import FleetManager

    pol = fleet_policy()
    check("fleet_enabled_config", pol.get("enabled"), str(pol))
    check("fleet_routing_available", fleet_routing_enabled())

    fm = FleetManager()
    health = fm.run_health_cycle(shadow=True)
    check("shadow_health_ran", health.get("checked", 0) >= 1)
    check("compute_up", health.get("up", 0) >= 2, f"up={health.get('up')}")

    ctx = fm.dispatch_context("Python programming language")
    check(
        "context_dispatch",
        ctx.get("success") or bool(ctx.get("provider_id")),
        str(ctx.get("error") or ctx.get("response", ""))[:80],
    )

    # Proxy path first -- realtime augment can block 90-150s on 3060 (T2 prefetch + Qwythos).
    payload = {
        "model": "phronesis-sovereign-auto",
        "messages": [{"role": "user", "content": "What happened today in AI news? One sentence."}],
        "max_tokens": 80,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8091/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    proxy_timeout = 180
    try:
        with urllib.request.urlopen(req, timeout=proxy_timeout) as resp:
            body = json.loads(resp.read().decode())
        content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        check("proxy_realtime_local", bool(str(content).strip()), "empty response")
    except Exception as exc:
        check("proxy_realtime_local", False, str(exc))

    t2 = try_t2_fleet_dispatch(
        "Summarize the latest trends in local LLM routers in 2 sentences.",
        {"task_type": "research"},
        local_failed=True,
    )
    check("t2_local_fail_dispatch", t2.get("success"), str(t2.get("error")))
    if t2.get("success"):
        check("t2_has_provider", bool(t2.get("provenance", {}).get("provider_id") or t2.get("model")))

    print(f"\n=== Results: {len(ERRORS)} failures ===")
    for e in ERRORS:
        print(f"  - {e}")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())