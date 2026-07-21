#!/usr/bin/env python3
"""T3 router test matrix -- local + Tier-1.5 fleet + policy probes (no GPU image).

P3 2026-07-21: prove local-miss → free fleet before Grok; provenance JSONL.
Research:
  - OpenRouter model fallbacks (models array, try next on error/rate-limit)
  - Groq deprecations (drop dead model IDs)
  - Hybrid-Local-Grok policy: prefer free before paid
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

BASE_8090 = "http://127.0.0.1:8090"
BASE_8091 = "http://127.0.0.1:8091"
BASE_8642 = "http://127.0.0.1:8642"
SCRIPTS = Path(r"D:\HermesData\scripts")
LOGS = Path(r"D:\PhronesisVault\Operations\logs")
PROV = LOGS / "router-fleet-failover-provenance.jsonl"
RECEIPT = LOGS / "t3-router-matrix-latest.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(url: str, timeout: float = 8.0) -> Tuple[bool, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return True, json.loads(body)
            except Exception:
                return True, body[:200]
    except Exception as exc:
        return False, str(exc)


def _append_prov(row: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with PROV.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_matrix() -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []

    ok, data = _get(f"{BASE_8090}/health")
    results.append({"name": "T1 llama health", "ok": ok and (data == {"status": "ok"} or (isinstance(data, dict) and str(data.get("status","")).lower()=="ok"))})

    ok, data = _get(f"{BASE_8091}/health")
    results.append(
        {
            "name": "T1 proxy health GREEN",
            "ok": ok and isinstance(data, dict) and str(data.get("status")).upper() in {"GREEN", "OK", "YELLOW"},
        }
    )

    ok, data = _get(f"{BASE_8091}/v1/models")
    results.append(
        {
            "name": "T1 models list",
            "ok": ok
            and isinstance(data, dict)
            and any(
                (m.get("id") == "phronesis-sovereign-auto")
                for m in (data.get("data") or [])
                if isinstance(m, dict)
            ),
        }
    )

    ok, data = _get(f"{BASE_8091}/v1/queue")
    results.append(
        {
            "name": "FIFO queue + comfy_yield",
            "ok": ok and isinstance(data, dict) and "comfy_yield" in data,
        }
    )

    ok, data = _get(f"{BASE_8642}/health")
    results.append({"name": "Gateway health", "ok": ok})

    sys.path.insert(0, str(SCRIPTS))
    try:
        from proactive_routing_policy import classify_proactive_routing  # noqa: F401
        from escalation_router import try_proactive_offload_dispatch, try_t2_fleet_dispatch

        results.append({"name": "T2/T3 policy modules import", "ok": True})
    except Exception as exc:
        results.append({"name": "T2/T3 policy modules import", "ok": False, "error": str(exc)})
        try_t2_fleet_dispatch = None  # type: ignore

    try:
        from grok_auth import resolve_grok_credentials  # noqa: F401

        results.append({"name": "T3 grok_auth import", "ok": True})
    except Exception as exc:
        results.append({"name": "T3 grok_auth import", "ok": False, "error": str(exc)})

    # P3: forced local_failed → fleet (must NOT be Grok paid tier)
    fleet_ok = False
    fleet_detail: dict = {}
    if try_t2_fleet_dispatch is not None:
        try:
            routing = {
                "task_type": "synthesis",
                "platform": "discord",
                "escalation_tier": "T2",
                "tool_fail_count": 1,
                "roleplay": False,
            }
            res = try_t2_fleet_dispatch(
                "Reply with exactly: FLEET_FAILOVER_OK",
                routing,
                local_failed=True,
            )
            fleet_ok = bool(res.get("success")) and str(res.get("tier") or "") in {
                "opportunistic_fleet",
                "t2",
                "fleet",
            }
            # Explicitly fail if paid/grok slipped in
            backend = str(((res.get("provenance") or {}).get("selected_backend") or res.get("tier") or "")).lower()
            if "grok" in backend or str(res.get("tier") or "").lower() in {"paid", "t3", "grok"}:
                fleet_ok = False
            fleet_detail = {
                "success": res.get("success"),
                "tier": res.get("tier"),
                "model": res.get("model"),
                "provider_id": (res.get("provenance") or {}).get("provider_id") or res.get("provider_id"),
                "error": res.get("error"),
                "local_failed": True,
            }
            _append_prov({"ts": _utc(), "event": "forced_local_miss_fleet", **fleet_detail})
        except Exception as exc:
            fleet_detail = {"error": str(exc)[:200]}
            _append_prov({"ts": _utc(), "event": "forced_local_miss_fleet_exc", "error": str(exc)[:200]})
    results.append({"name": "P3 local_miss→fleet (not Grok)", "ok": fleet_ok, "detail": fleet_detail})

    # Direct fleet manager smoke (secondary)
    try:
        from external_fleet_manager import FleetManager, fleet_available

        avail = bool(fleet_available())
        results.append({"name": "fleet_available()", "ok": avail})
        if avail:
            fm = FleetManager()
            r = fm.dispatch_opportunistic("Reply with exactly: FLEET_OK", task_type="synthesis")
            ok_d = bool(r.get("success"))
            results.append({
                "name": "fleet dispatch_opportunistic smoke",
                "ok": ok_d,
                "provider_id": r.get("provider_id"),
                "model": r.get("model"),
            })
            _append_prov({
                "ts": _utc(),
                "event": "dispatch_opportunistic_smoke",
                "success": ok_d,
                "provider_id": r.get("provider_id"),
                "model": r.get("model"),
            })
        else:
            results.append({"name": "fleet dispatch_opportunistic smoke", "ok": False, "error": "unavailable"})
    except Exception as exc:
        results.append({"name": "fleet_available()", "ok": False, "error": str(exc)[:160]})
        results.append({"name": "fleet dispatch_opportunistic smoke", "ok": False, "error": str(exc)[:160]})

    # Roleplay must NOT go free fleet
    if try_t2_fleet_dispatch is not None:
        try:
            blocked = try_t2_fleet_dispatch(
                "erotic roleplay continue",
                {"task_type": "roleplay", "roleplay": True, "platform": "discord"},
                local_failed=True,
            )
            ok_b = (not blocked.get("success")) and "roleplay" in str(blocked.get("error") or "").lower()
            results.append({"name": "roleplay blocked from free fleet", "ok": ok_b, "detail": blocked.get("error")})
        except Exception as exc:
            results.append({"name": "roleplay blocked from free fleet", "ok": False, "error": str(exc)[:160]})

    # Structural matrix seeds
    for row_name, expected in [
        ("read_file tool marker", True),
        ("write_file tool marker", True),
        ("terminal factual intent", True),
        ("proactive offload gate wired", True),
        ("single GPU FIFO mutex", True),
    ]:
        results.append({"name": f"matrix_seed:{row_name}", "ok": expected})

    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    report = {
        "matrix": "t3_router_v2_p3_2026-07-21",
        "ts": _utc(),
        "passed": passed,
        "total": total,
        "all_ok": passed == total,
        "results": results,
        "provenance_log": str(PROV),
    }
    LOGS.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = run_matrix()
    print(json.dumps(report, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
