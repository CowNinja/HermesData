#!/usr/bin/env python3
"""
escalation_router.py -- T2 (free fleet) + T3 (paid) escalation for sovereign proxy.

Local-first invariant:
  - Qwythos @ :8090 is always attempted first (native passthrough).
  - T2 supplements on: local failure, proactive realtime triggers (context augment),
    or explicit escalation_tier=T2 (tool stress).
  - T3 only on explicit escalation_tier=T3 or high-stakes triggers -- never roleplay.

Config gate: local_sovereign.opportunistic_fleet.enabled in config.yaml
Registry: config/fleet_registry.yaml
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES_ROOT = Path(r"D:\HermesData")
CONFIG_PATH = HERMES_ROOT / "config.yaml"
VAULT_LOG = Path(r"D:\PhronesisVault\Operations\logs\escalation-router.jsonl")

ROLEPLAY_PLATFORMS = frozenset({
    "alice-roleplay",
    "discord-roleplay",
    "roleplay",
    "immersive_roleplay",
})

_FLEET_POLICY_CACHE: Dict[str, Any] = {"loaded_at": 0.0, "policy": {}}
_FLEET_POLICY_TTL_SEC = 30.0


def _log(event: Dict[str, Any]) -> None:
    try:
        VAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VAULT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def fleet_policy() -> Dict[str, Any]:
    """Merged fleet policy from config.yaml + defaults (cached)."""
    now = time.time()
    cached = _FLEET_POLICY_CACHE.get("policy") or {}
    if cached and (now - float(_FLEET_POLICY_CACHE.get("loaded_at") or 0.0)) < _FLEET_POLICY_TTL_SEC:
        return dict(cached)
    raw = _load_yaml(CONFIG_PATH)
    fleet = (raw.get("local_sovereign") or {}).get("opportunistic_fleet") or {}
    policy = {
        "enabled": bool(fleet.get("enabled")),
        "prefer_free_before_grok": bool(fleet.get("prefer_free_before_grok", True)),
        "augment_local_with_context": bool(fleet.get("augment_local_with_context", True)),
        "fallback_on_local_fail": bool(fleet.get("fallback_on_local_fail", True)),
        "proactive_realtime_triggers": bool(fleet.get("proactive_realtime_triggers", True)),
        "proactive_offload": bool(fleet.get("proactive_offload", True)),
        "registry": str(fleet.get("registry") or HERMES_ROOT / "config" / "fleet_registry.yaml"),
        "block_roleplay": True,
    }
    _FLEET_POLICY_CACHE["loaded_at"] = now
    _FLEET_POLICY_CACHE["policy"] = policy
    return dict(policy)


def fleet_routing_enabled() -> bool:
    pol = fleet_policy()
    if not pol.get("enabled"):
        return False
    try:
        from external_fleet_manager import fleet_available

        return fleet_available()
    except Exception:
        return False


def is_roleplay_route(routing: Optional[Dict[str, Any]]) -> bool:
    route = routing or {}
    if route.get("force_roleplay"):
        return True
    if str(route.get("task_type") or "").lower() in ("roleplay", "narrative", "rp"):
        return True
    platform = str(route.get("platform") or "").lower()
    if platform in ROLEPLAY_PLATFORMS or "roleplay" in platform:
        return True
    model = str(route.get("model") or "").lower()
    if "roleplay" in model or model.endswith("-rp"):
        return True
    return False


def _prefetch_timeout_sec() -> float:
    pol = fleet_policy()
    try:
        reg = _load_yaml(Path(pol.get("registry") or HERMES_ROOT / "config" / "fleet_registry.yaml"))
        rules = (reg.get("procurement") or {}).get("pass_rules") or {}
        return float(rules.get("context_latency_max_sec") or 20)
    except Exception:
        return 20.0


def _dispatch_context_bounded(
    dispatch_fn: Any,
    query: str,
    *,
    capabilities: List[str],
) -> Dict[str, Any]:
    """Bounded T2 context prefetch -- augment is optional; never block local path indefinitely."""
    timeout_sec = _prefetch_timeout_sec()
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(dispatch_fn, query, capabilities=capabilities)
        try:
            return fut.result(timeout=timeout_sec)
        except FuturesTimeout:
            return {
                "success": False,
                "error": "context_prefetch_timeout",
                "timeout_sec": timeout_sec,
            }


def _fleet_triggers(prompt: str, routing: Dict[str, Any], *, local_failed: bool = False) -> Dict[str, Any]:
    from router_bridge import detect_opportunistic_fleet_triggers

    return detect_opportunistic_fleet_triggers(
        prompt=prompt,
        task_type=routing.get("task_type"),
        context_tokens_estimate=len(prompt) // 4 + 4000,
        local_failed=local_failed,
    )


def _prepare_fleet_prompt(prompt: str, routing: Dict[str, Any]) -> tuple[bool, str, str]:
    """Sanitize and block fleet/T3 dispatch when private, explicit, or ambiguous unsafe."""
    from proactive_routing_policy import (
        contains_sensitive_content,
        is_fleet_safe_for_offload,
        sanitize_for_fleet,
    )

    if is_roleplay_route(routing):
        return False, "roleplay_blocked", prompt
    sensitive, reason = contains_sensitive_content(prompt)
    if sensitive:
        return False, reason, prompt
    sanitized = sanitize_for_fleet(prompt)
    safe, block = is_fleet_safe_for_offload(sanitized)
    if not safe:
        return False, block, prompt
    return True, "", sanitized


def maybe_augment_messages_with_context(
    messages: List[Dict[str, Any]],
    prompt: str,
    routing: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    T2 augment mode: prefetch real-time context into messages before local dispatch.
    Does not replace local inference -- supplements working memory only.
    """
    meta: Dict[str, Any] = {"augmented": False}
    pol = fleet_policy()
    if not pol.get("enabled") or not pol.get("augment_local_with_context"):
        return messages, meta
    if is_roleplay_route(routing):
        return messages, meta
    triggers = _fleet_triggers(prompt, routing, local_failed=False)
    if not triggers.get("should_route"):
        return messages, meta
    if "latest_external_knowledge" not in (triggers.get("matched_triggers") or []):
        if not pol.get("proactive_realtime_triggers"):
            return messages, meta
    try:
        from external_fleet_manager import FleetManager

        fm = FleetManager()
        ctx = _dispatch_context_bounded(
            fm.dispatch_context_cached,
            prompt[:600],
            capabilities=["real-time-search"],
        )
        if not ctx.get("success"):
            meta["augment_skipped"] = ctx.get("error") or "context_dispatch_failed"
            return messages, meta
        block = str(ctx.get("response") or "").strip()
        if not block:
            return messages, meta
        snippet = block[:4000]
        note = {
            "role": "system",
            "content": (
                "[T2 CONTEXT AUGMENT -- opportunistic fleet prefetch; verify before citing]\n"
                + snippet
            ),
        }
        out = list(messages)
        out.insert(0, note)
        meta.update({
            "augmented": True,
            "provider_id": ctx.get("provider_id"),
            "triggers": triggers.get("matched_triggers"),
        })
        _log({"event": "context_augment", **meta})
        return out, meta
    except Exception as exc:
        meta["augment_error"] = str(exc)
        return messages, meta


def try_t2_fleet_dispatch(
    prompt: str,
    routing: Dict[str, Any],
    *,
    local_failed: bool = False,
) -> Dict[str, Any]:
    """Tier 1.5 -- free compute + optional context via external_fleet_manager."""
    started = time.time()
    pol = fleet_policy()
    if not pol.get("enabled"):
        return {"success": False, "tier": "opportunistic_fleet", "error": "fleet_disabled_in_config"}
    if is_roleplay_route(routing):
        return {"success": False, "tier": "opportunistic_fleet", "error": "roleplay_blocked"}

    ok, block_reason, fleet_prompt = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        return {
            "success": False,
            "tier": "opportunistic_fleet",
            "error": f"fleet_blocked:{block_reason}",
        }

    triggers = _fleet_triggers(fleet_prompt, routing, local_failed=local_failed)
    tier = str(routing.get("escalation_tier") or "")
    force_t2 = tier == "T2" and int(routing.get("tool_fail_count") or 0) > 0
    if not local_failed and not force_t2 and not triggers.get("should_route"):
        return {
            "success": False,
            "tier": "opportunistic_fleet",
            "error": "no_fleet_triggers",
            "triggers": triggers,
        }
    if local_failed and not pol.get("fallback_on_local_fail"):
        return {"success": False, "tier": "opportunistic_fleet", "error": "fallback_disabled"}

    try:
        from external_fleet_manager import FleetManager, fleet_available

        if not fleet_available():
            return {"success": False, "tier": "opportunistic_fleet", "error": "fleet_unavailable"}
        fm = FleetManager()
        include_ctx = (
            "latest_external_knowledge" in (triggers.get("matched_triggers") or [])
            or force_t2
        )
        res = fm.dispatch_opportunistic(
            fleet_prompt,
            task_type=routing.get("task_type"),
            triggers=triggers.get("matched_triggers"),
            include_context=include_ctx,
        )
        if not res.get("success"):
            _log({"event": "t2_fail", "error": res.get("error"), "triggers": triggers.get("matched_triggers")})
            return {
                "success": False,
                "tier": "opportunistic_fleet",
                "error": res.get("error"),
                "provenance": {"selected_backend": "opportunistic_fleet", "triggers": triggers.get("matched_triggers")},
            }
        latency = round(time.time() - started, 2)
        out = {
            "success": True,
            "response": str(res.get("response") or ""),
            "model": res.get("model"),
            "tier": "opportunistic_fleet",
            "latency_sec": latency,
            "provenance": {
                "selected_backend": "opportunistic_fleet",
                "escalation_tier": "T2",
                "provider_id": res.get("provider_id"),
                "provider_name": res.get("provider_name"),
                "fleet_triggers": triggers.get("matched_triggers"),
                "context_prefetch": res.get("context_prefetch"),
                "local_failed": local_failed,
            },
        }
        _log({"event": "t2_ok", "provider_id": res.get("provider_id"), "latency_sec": latency})
        return out
    except Exception as exc:
        return {
            "success": False,
            "tier": "opportunistic_fleet",
            "error": str(exc),
            "provenance": {"selected_backend": "opportunistic_fleet", "error": str(exc)},
        }


def try_t3_paid_dispatch(prompt: str, routing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tier 3 -- heavy reasoning. Tries free fleet first when prefer_free_before_grok.

    Grok auth via grok_auth.py (subscription OAuth first, console API key fallback).
    """
    if is_roleplay_route(routing):
        return {"success": False, "tier": "paid", "error": "roleplay_blocked"}

    ok, block_reason, fleet_prompt = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        return {"success": False, "tier": "paid", "error": f"fleet_blocked:{block_reason}"}

    pol = fleet_policy()
    if pol.get("prefer_free_before_grok"):
        t2 = try_t2_fleet_dispatch(fleet_prompt, routing, local_failed=True)
        if t2.get("success"):
            prov = t2.setdefault("provenance", {})
            prov["t3_deferred_to_t2"] = True
            return t2

    from grok_auth import grok_user_prompt_completion

    result = grok_user_prompt_completion(fleet_prompt)
    if result.get("success"):
        prov = result.setdefault("provenance", {})
        prov["escalation_tier"] = "T3"
        _log({
            "event": "t3_ok",
            "model": result.get("model"),
            "billing": prov.get("billing"),
            "auth_provider": prov.get("provider"),
            "latency_sec": result.get("latency_sec"),
        })
        return result

    err_msg = str(result.get("error") or result.get("response") or "t3_dispatch_failed")
    _log({"event": "t3_fail", "error": err_msg})
    return {
        "success": False,
        "escalation": True,
        "tier": "grok_escalation",
        "response": f"[T3 PAID ESCALATION] {err_msg}",
        "provenance": result.get("provenance") or {
            "selected_backend": "paid_grok",
            "escalation_tier": "T3",
        },
    }


def _proactive_wants_t3(prompt: str, routing: Dict[str, Any]) -> bool:
    tier = str(routing.get("escalation_tier") or "")
    if tier == "T3":
        return True
    low = (prompt or "").lower()
    heavy_markers = (
        "heavy reasoning",
        "grok heavy",
        "super grok",
        "tier 3",
        "t3 escalate",
        "architecture",
        "system design",
        "deep synthesis",
        "multi-hour",
    )
    if any(m in low for m in heavy_markers):
        return True
    if int(routing.get("tool_fail_count") or 0) > 2:
        return True
    return False


def try_proactive_t2_dispatch(prompt: str, routing: Dict[str, Any]) -> Dict[str, Any]:
    """Proactive T2 - free fleet compute for classified public/non-private work."""
    pol = fleet_policy()
    if not pol.get("enabled") or not fleet_routing_enabled():
        return {"success": False, "tier": "opportunistic_fleet", "error": "fleet_unavailable"}
    if is_roleplay_route(routing):
        return {"success": False, "tier": "opportunistic_fleet", "error": "roleplay_blocked"}
    ok, block_reason, fleet_prompt = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        return {
            "success": False,
            "tier": "opportunistic_fleet",
            "error": f"fleet_blocked:{block_reason}",
        }
    try:
        from external_fleet_manager import FleetManager

        fm = FleetManager()
        triggers = _fleet_triggers(fleet_prompt, routing, local_failed=False)
        include_ctx = "latest_external_knowledge" in (triggers.get("matched_triggers") or [])
        res = fm.dispatch_opportunistic(
            fleet_prompt,
            task_type=routing.get("task_type"),
            triggers=triggers.get("matched_triggers") or ["proactive_offload"],
            include_context=include_ctx,
        )
        if res.get("success"):
            res.setdefault("provenance", {})
            res["provenance"].update({
                "selected_backend": "opportunistic_fleet",
                "escalation_tier": "T2",
                "proactive_offload": True,
                "routing_mode": "offload_t2",
            })
            _log({"event": "proactive_t2_ok", "provider_id": res.get("provider_id")})
        return res
    except Exception as exc:
        return {"success": False, "tier": "opportunistic_fleet", "error": str(exc)}


def try_proactive_offload_dispatch(
    prompt: str,
    routing: Dict[str, Any],
    messages: List[Dict[str, Any]],
    body: Optional[Dict[str, Any]] = None,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Proactive distributed routing - skip local GPU when work is public/non-private.

    Ladder: T2 free fleet -> T3 Super Grok (xAI) for heavy reasoning -> else local fallback.
    """
    pol = fleet_policy()
    if not pol.get("proactive_offload", True):
        return {"success": False, "proactive_offload": False, "skipped": "proactive_disabled"}

    try:
        from inference_queue import should_defer_proactive_offload

        defer, defer_reason = should_defer_proactive_offload()
        if defer:
            return {
                "success": False,
                "proactive_offload": False,
                "skipped": "gpu_fifo_busy",
                "reasons": [defer_reason],
            }
    except Exception as exc:
        _log({"event": "proactive_offload_defer_check_error", "error": str(exc)})

    from proactive_routing_policy import ROUTING_OFFLOAD_COMPUTE, classify_proactive_routing

    classification = classify_proactive_routing(
        prompt, routing, messages, body or {}, headers=headers or {},
    )
    if classification.get("mode") != ROUTING_OFFLOAD_COMPUTE:
        return {
            "success": False,
            "proactive_offload": False,
            "skipped": classification.get("mode"),
            "reasons": classification.get("reasons"),
        }

    safe_prompt = str(classification.get("sanitized_prompt") or prompt)
    wants_t3 = _proactive_wants_t3(safe_prompt, routing)

    t2_result: Dict[str, Any] = {"success": False}
    if not wants_t3:
        t2_result = try_proactive_t2_dispatch(safe_prompt, routing)
        if t2_result.get("success"):
            t2_result["classification"] = classification
            return t2_result

    if wants_t3 or pol.get("prefer_free_before_grok"):
        if wants_t3 and pol.get("enabled") and fleet_routing_enabled():
            t2_result = try_proactive_t2_dispatch(safe_prompt, routing)
            if t2_result.get("success"):
                t2_result["classification"] = classification
                return t2_result

    t3_route = {**routing, "escalation_tier": "T3"}
    t3_result = try_t3_paid_dispatch(safe_prompt, t3_route)
    if t3_result.get("success"):
        t3_result.setdefault("provenance", {})
        t3_result["provenance"]["proactive_offload"] = True
        t3_result["provenance"]["routing_mode"] = "offload_t3"
        t3_result["classification"] = classification
        _log({"event": "proactive_t3_ok", "model": t3_result.get("model")})
        return t3_result

    if t2_result.get("success"):
        return t2_result

    return {
        "success": False,
        "proactive_offload": False,
        "skipped": "offload_ladder_failed",
        "t2_error": t2_result.get("error"),
        "t3_error": t3_result.get("error"),
        "reasons": classification.get("reasons"),
    }


def resolve_post_local_dispatch(
    prompt: str,
    routing: Dict[str, Any],
    local_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    After native/bridge local attempt: apply T2 fallback then T3 if configured.
    """
    if local_result.get("success"):
        prov = local_result.setdefault("provenance", {})
        if prov.get("context_augment"):
            return local_result
        return local_result

    ok, block_reason, fleet_prompt = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        local_result.setdefault("provenance", {})["fleet_escalation_blocked"] = block_reason
        return local_result

    tier = str(routing.get("escalation_tier") or "")
    if fleet_routing_enabled():
        t2 = try_t2_fleet_dispatch(fleet_prompt, routing, local_failed=True)
        if t2.get("success"):
            return t2

    if tier == "T3":
        return try_t3_paid_dispatch(fleet_prompt, routing)

    if tier == "T2" and fleet_routing_enabled():
        t2 = try_t2_fleet_dispatch(fleet_prompt, routing, local_failed=False)
        if t2.get("success"):
            return t2

    return local_result