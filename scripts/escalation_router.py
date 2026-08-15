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
PROVENANCE_LOG = Path(r"D:\PhronesisVault\Operations\logs\router-fleet-failover-provenance.jsonl")

ROLEPLAY_PLATFORMS = frozenset({
    "alice-roleplay",
    "discord-roleplay",
    "roleplay",
    "immersive_roleplay",
})

# W3-P2 hop constants (mirrored; pick_backend is SSOT when importable)
BACKEND_LOCAL = "local"
BACKEND_FREE = "free"
BACKEND_GROK = "grok"
DEFAULT_HOP = (BACKEND_LOCAL, BACKEND_FREE, BACKEND_GROK)

_FLEET_POLICY_CACHE: Dict[str, Any] = {"loaded_at": 0.0, "policy": {}}
_FLEET_POLICY_TTL_SEC = 30.0


def _append_provenance(event: Dict[str, Any]) -> None:
    """Append durable failover provenance (W2-P1/P5 thrift signal)."""
    try:
        from datetime import datetime, timezone
        row = dict(event)
        row.setdefault("ts", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        PROVENANCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PROVENANCE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
    except Exception:
        pass


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
    # Prefer config.yaml; also honor fleet_registry policy aliases if present later.
    fallback_local = fleet.get("fallback_on_local_fail")
    if fallback_local is None:
        fallback_local = fleet.get("local_failover_to_fleet", True)
    policy = {
        "enabled": bool(fleet.get("enabled")),
        "prefer_free_before_grok": bool(fleet.get("prefer_free_before_grok", True)),
        "augment_local_with_context": bool(fleet.get("augment_local_with_context", True)),
        "fallback_on_local_fail": bool(fallback_local),
        "local_failover_to_fleet": bool(fallback_local),  # alias SSOT
        "proactive_realtime_triggers": bool(fleet.get("proactive_realtime_triggers", True)),
        "proactive_offload": bool(fleet.get("proactive_offload", True)),
        # Policy B: auto T3 for hard prompts; share caps mirror thrift gate
        "grok_policy": str(fleet.get("grok_policy") or "B").upper(),
        "hard_prompt_auto_t3": bool(fleet.get("hard_prompt_auto_t3", True)),
        "grok_share_cap_yellow": float(fleet.get("grok_share_cap_yellow", 0.12)),
        "grok_share_cap_red": float(fleet.get("grok_share_cap_red", 0.28)),
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


# Named hire surface only. Jeff walks into this thread on purpose.
# Hop stays proxy T3 (Grok 4.6) — never pin xai-oauth on Discord overrides.
GROK_HIRE_CHAT_IDS = frozenset(
    {
        "1524846849360531456",  # Grok coord / Grok 4.6
    }
)


def is_grok_hire_chat(routing: Optional[Dict[str, Any]] = None) -> bool:
    """True only for the named Grok coord thread. Garden/RP never."""
    if is_roleplay_route(routing):
        return False
    route = routing or {}
    ids = {
        str(route.get("chat_id") or "").strip(),
        str(route.get("thread_id") or "").strip(),
        str(route.get("parent_channel_id") or "").strip(),
    }
    return bool(ids & GROK_HIRE_CHAT_IDS)


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


def _prepare_fleet_prompt(prompt: str, routing: Dict[str, Any]) -> tuple[bool, str, str, Dict[str, str]]:
    """Mask + gate fleet/T3 dispatch. Returns (ok, block_reason, fleet_prompt, mask_map).

    Phase 4: deterministic handle mask (privacy_mask_rehydrate). Fail closed for
    RP / explicit / HIPAA / hard identity. Mask map used to rehydrate responses.
    """
    if is_roleplay_route(routing):
        return False, "roleplay_blocked", prompt, {}
    try:
        from privacy_mask_rehydrate import prepare_structural_offload, rehydrate_result  # noqa: F401

        prep = prepare_structural_offload(prompt or "", routing=routing)
        if not prep.get("allow"):
            return False, str(prep.get("block_reason") or "fleet_blocked"), prompt, {}
        return (
            True,
            "",
            str(prep.get("fleet_prompt") or prompt),
            dict(prep.get("mask_map") or {}),
        )
    except Exception:
        pass
    # Fallback legacy path
    from proactive_routing_policy import (
        contains_sensitive_content,
        is_fleet_safe_for_offload,
        sanitize_for_fleet,
    )

    sensitive, reason = contains_sensitive_content(prompt)
    if sensitive:
        return False, reason, prompt, {}
    sanitized = sanitize_for_fleet(prompt)
    safe, block = is_fleet_safe_for_offload(sanitized)
    if not safe:
        return False, block, prompt, {}
    return True, "", sanitized, {}


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

    ok, block_reason, fleet_prompt, mask_map = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        return {
            "success": False,
            "tier": "opportunistic_fleet",
            "error": f"fleet_blocked:{block_reason}",
        }

    # Phase 5: structural semantic cache (post-mask fleet_prompt only; fail-closed miss)
    try:
        from semantic_cache import cache_lookup_for_dispatch, cache_store_from_dispatch
        from privacy_mask_rehydrate import rehydrate_result as _rehydrate_cached

        cached = cache_lookup_for_dispatch(fleet_prompt, routing)
        if cached and cached.get("success"):
            cached = _rehydrate_cached(cached, mask_map)
            cached.setdefault("provenance", {})["privacy_mask_spans"] = len(mask_map or {})
            cached["latency_sec"] = round(time.time() - started, 2)
            _log({
                "event": "t2_cache_hit",
                "match_kind": cached.get("cache_match_kind"),
                "score": cached.get("cache_score"),
            })
            return cached
    except Exception:
        pass

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
        from privacy_mask_rehydrate import rehydrate_result

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
            "provider_id": res.get("provider_id"),
            "triggers": triggers.get("matched_triggers"),
            "context_prefetch": res.get("context_prefetch"),
            "context_only": res.get("context_only"),
            "provenance": {
                "selected_backend": "opportunistic_fleet",
                "escalation_tier": "T2",
                "provider_id": res.get("provider_id"),
                "provider_name": res.get("provider_name"),
                "fleet_triggers": triggers.get("matched_triggers"),
                "context_prefetch": res.get("context_prefetch"),
                "local_failed": local_failed,
                "privacy_mask_spans": len(mask_map or {}),
            },
        }
        # Phase 5: remember pre-rehydrate body (handles only; no raw mask map on disk)
        try:
            from semantic_cache import cache_store_from_dispatch

            cache_store_from_dispatch(fleet_prompt, out, routing)
        except Exception:
            pass
        out = rehydrate_result(out, mask_map)
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
    Tier 3 -- heavy reasoning. Grok first, free backup.

    prefer_free_before_grok is grunt law (T1/T2). Public brains skip 9B/free
    as the first thinker. Garden / RP never enter this function.
    Grok auth via grok_auth.py (subscription OAuth first, console API key fallback).
    """
    if is_roleplay_route(routing):
        return {"success": False, "tier": "paid", "error": "roleplay_blocked"}

    ok, block_reason, fleet_prompt, mask_map = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        return {"success": False, "tier": "paid", "error": f"fleet_blocked:{block_reason}"}

    from grok_auth import grok_user_prompt_completion
    from privacy_mask_rehydrate import rehydrate_result

    result = grok_user_prompt_completion(fleet_prompt)
    if result.get("success"):
        result = rehydrate_result(result, mask_map)
        prov = result.setdefault("provenance", {})
        prov["escalation_tier"] = "T3"
        prov["selected_backend"] = "grok"
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

    # Free backup after Grok miss — never the other way around on T3
    t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=True)
    if t2.get("success"):
        prov = t2.setdefault("provenance", {})
        prov["t3_fallback_to_t2"] = True
        prov["t3_grok_error"] = err_msg[:240]
        return t2

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


def _grok_share_blocks_t3() -> tuple[bool, str]:
    """Policy B thrift guard: block auto T3 when rolling Grok share already at/above RED."""
    try:
        rollup_path = HERMES_ROOT / "state" / "router-thrift-rollup-latest.json"
        if not rollup_path.is_file():
            rollup_path = HERMES_ROOT / "state" / "router_thrift_rollup_latest.json"
        if not rollup_path.is_file():
            return False, "no_rollup"
        data = json.loads(rollup_path.read_text(encoding="utf-8"))
        thrift = data.get("thrift") if isinstance(data.get("thrift"), dict) else {}
        share = data.get("share") if isinstance(data.get("share"), dict) else {}
        local_n = int(thrift.get("local") or 0)
        free_n = int(thrift.get("free") or 0)
        grok_n = int(thrift.get("grok") or 0)
        total = local_n + free_n + grok_n
        if total < 10:
            return False, "low_sample"
        grok_s = float(share.get("grok") or (grok_n / total if total else 0.0))
        pol = fleet_policy()
        red = float(pol.get("grok_share_cap_red") or 0.20)
        if grok_s >= red:
            return True, f"grok_share_red:{grok_s:.3f}>={red}"
        return False, f"grok_share_ok:{grok_s:.3f}"
    except Exception as exc:
        return False, f"share_check_err:{exc}"


def _proactive_wants_t3(prompt: str, routing: Dict[str, Any]) -> bool:
    """
    Policy B hard-prompt detector.

    Grok only when work needs reasoning/planning beyond local+free:
    architecture, multi-step design, judgment, or repeated tool failure.
    Explicit T3 / driver always wins. Roleplay never.
    """
    pol = fleet_policy()
    tier = str(routing.get("escalation_tier") or "")
    if tier == "T3":
        return True
    if str(routing.get("force_grok") or "").lower() in ("1", "true", "yes"):
        return True
    if is_grok_hire_chat(routing):
        return True
    # Policy A was driver-only rare; Policy B enables marker auto-T3 (default).
    if not pol.get("hard_prompt_auto_t3", True) and str(pol.get("grok_policy") or "B") == "A":
        return False
    # Spend kind SSOT: token_resource_governor (explicit / strong / modest).
    # Hop color (RED strips Grok) is applied in pick_backend, not here.
    try:
        from token_resource_governor import spend_kind

        kind = spend_kind(prompt, routing)
    except Exception:
        kind = "none"
        low = (prompt or "").lower()
        if any(
            m in low
            for m in (
                "needs grok",
                "escalate to grok",
                "beyond local",
                "t3 escalate",
                "tier 3",
                "super grok",
                "grok heavy",
            )
        ):
            kind = "explicit"
        elif "tradeoff analysis" in low or "root cause analysis" in low:
            kind = "auto_strong"
    if kind == "explicit":
        return True
    if kind in {"auto_strong", "auto_modest"} or int(routing.get("tool_fail_count") or 0) > 2:
        blocked, reason = _grok_share_blocks_t3()
        if blocked:
            _log({"event": "t3_blocked_share_cap", "reason": reason})
            return False
        return True
    return False


def try_proactive_t2_dispatch(prompt: str, routing: Dict[str, Any]) -> Dict[str, Any]:
    """Proactive T2 - free fleet compute for classified public/non-private work."""
    pol = fleet_policy()
    if not pol.get("enabled") or not fleet_routing_enabled():
        return {"success": False, "tier": "opportunistic_fleet", "error": "fleet_unavailable"}
    if is_roleplay_route(routing):
        return {"success": False, "tier": "opportunistic_fleet", "error": "roleplay_blocked"}
    ok, block_reason, fleet_prompt, mask_map = _prepare_fleet_prompt(prompt, routing)
    if not ok:
        return {
            "success": False,
            "tier": "opportunistic_fleet",
            "error": f"fleet_blocked:{block_reason}",
        }
    # Phase 5: structural semantic cache before free hop
    try:
        from semantic_cache import cache_lookup_for_dispatch
        from privacy_mask_rehydrate import rehydrate_result as _rehydrate_cached

        cached = cache_lookup_for_dispatch(fleet_prompt, routing)
        if cached and cached.get("success"):
            cached = _rehydrate_cached(cached, mask_map)
            cached.setdefault("provenance", {}).update({
                "proactive_offload": True,
                "routing_mode": "offload_t2",
                "privacy_mask_spans": len(mask_map or {}),
            })
            _log({
                "event": "proactive_t2_cache_hit",
                "match_kind": cached.get("cache_match_kind"),
            })
            return cached
    except Exception:
        pass
    try:
        from external_fleet_manager import FleetManager
        from privacy_mask_rehydrate import rehydrate_result

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
                "privacy_mask_spans": len(mask_map or {}),
            })
            # Phase 5: store pre-rehydrate free body only
            try:
                from semantic_cache import cache_store_from_dispatch

                cache_store_from_dispatch(fleet_prompt, res, routing)
            except Exception:
                pass
            res = rehydrate_result(res, mask_map)
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

    # Local GPU contention (image lock / dual / 8090 down) ? prefer fleet for non-RP.
    prefer_fleet = False
    prefer_reason = ""
    try:
        from inference_queue import should_prefer_fleet_offload, should_defer_proactive_offload

        prefer_fleet, prefer_reason = should_prefer_fleet_offload()
        if not prefer_fleet:
            defer, defer_reason = should_defer_proactive_offload()
            if defer:
                return {
                    "success": False,
                    "proactive_offload": False,
                    "skipped": "gpu_fifo_busy",
                    "reasons": [defer_reason],
                }
        else:
            _log({"event": "proactive_offload_prefer_fleet", "reason": prefer_reason})
    except Exception as exc:
        _log({"event": "proactive_offload_defer_check_error", "error": str(exc)})

    from proactive_routing_policy import (
        ROUTING_OFFLOAD_COMPUTE,
        ROUTING_LOCAL_FIRST,
        ROUTING_LOCAL_ONLY,
        ROUTING_AUGMENT_LOCAL,
        classify_proactive_routing,
    )

    classification = classify_proactive_routing(
        prompt, routing, messages, body or {}, headers=headers or {},
    )
    mode = str(classification.get("mode") or "")
    # Named hire room: force public-brains offload so T3 runs first.
    # Still fail-closed on garden/RP (is_grok_hire_chat already false there).
    if is_grok_hire_chat(routing) and mode not in {
        ROUTING_LOCAL_ONLY,
        "local_only",
        "local_private",
        ROUTING_AUGMENT_LOCAL,
        "augment_local",
    }:
        classification = dict(classification)
        classification["mode"] = ROUTING_OFFLOAD_COMPUTE
        reasons = list(classification.get("reasons") or [])
        reasons.append("named_grok_hire_surface")
        classification["reasons"] = reasons
        mode = ROUTING_OFFLOAD_COMPUTE
    # When local is contended/down, hard-upgrade safe non-private modes to free fleet.
    # Never upgrade local_only / RP / private / augment_local (sandbox stays local).
    # Prefer free before Grok ? token-outage resilience (2026-07-27).
    private_modes = {
        ROUTING_LOCAL_ONLY,
        "local_only",
        "local_private",
        ROUTING_AUGMENT_LOCAL,
        "augment_local",
    }
    upgradeable_modes = {
        ROUTING_LOCAL_FIRST,
        "local_first",
        "local_default",
        "keep_local",
        "local",
    }
    if mode != ROUTING_OFFLOAD_COMPUTE:
        if prefer_fleet and mode in upgradeable_modes:
            from_mode = mode
            classification = dict(classification)
            classification["mode"] = ROUTING_OFFLOAD_COMPUTE
            classification["prefer_fleet_reason"] = prefer_reason
            classification["hard_prefer_fleet"] = True
            reasons = list(classification.get("reasons") or [])
            reasons.append(f"hard_prefer_fleet:{prefer_reason}")
            classification["reasons"] = reasons
            mode = ROUTING_OFFLOAD_COMPUTE
            _log(
                {
                    "event": "proactive_offload_hard_upgrade",
                    "from_mode": from_mode,
                    "reason": prefer_reason,
                }
            )
        elif prefer_fleet and mode in private_modes:
            return {
                "success": False,
                "proactive_offload": False,
                "skipped": mode,
                "reasons": list(classification.get("reasons") or [])
                + [f"prefer_fleet_blocked:{prefer_reason}"],
            }
        else:
            return {
                "success": False,
                "proactive_offload": False,
                "skipped": classification.get("mode"),
                "reasons": classification.get("reasons"),
            }
    if prefer_fleet:
        classification = dict(classification)
        classification["prefer_fleet_reason"] = prefer_reason

    safe_prompt = str(classification.get("sanitized_prompt") or prompt)
    wants_t3 = _proactive_wants_t3(safe_prompt, routing)

    t2_result: Dict[str, Any] = {"success": False}
    t3_result: Dict[str, Any] = {"success": False}

    # Public brains: Grok first, free backup. Grunt: free first (prefer_free law).
    if wants_t3:
        t3_route = {**routing, "escalation_tier": "T3"}
        t3_result = try_t3_paid_dispatch(prompt, t3_route)
        if t3_result.get("success"):
            t3_result.setdefault("provenance", {})
            t3_result["provenance"]["proactive_offload"] = True
            t3_result["provenance"]["routing_mode"] = "offload_t3"
            t3_result["classification"] = classification
            _log({"event": "proactive_t3_ok", "model": t3_result.get("model")})
            return t3_result
        t2_result = try_proactive_t2_dispatch(prompt, routing)
        if t2_result.get("success"):
            t2_result["classification"] = classification
            t2_result.setdefault("provenance", {})["t3_fallback_to_t2"] = True
            return t2_result
    else:
        # Grunt / prefer_fleet: free first. Dispatch original prompt so
        # privacy_mask_rehydrate owns mask_map + rehydrate (not double-mask).
        t2_result = try_proactive_t2_dispatch(prompt, routing)
        if t2_result.get("success"):
            t2_result["classification"] = classification
            if prefer_fleet:
                t2_result.setdefault("provenance", {})["prefer_fleet_reason"] = prefer_reason
            return t2_result

    return {
        "success": False,
        "proactive_offload": False,
        "skipped": "offload_ladder_failed",
        "t2_error": t2_result.get("error"),
        "t3_error": t3_result.get("error"),
        "reasons": classification.get("reasons"),
        "prefer_fleet": prefer_fleet,
        "prefer_fleet_reason": prefer_reason if prefer_fleet else None,
    }


def resolve_post_local_dispatch(
    prompt: str,
    routing: Dict[str, Any],
    local_result: Dict[str, Any],
) -> Dict[str, Any]:
    """After native/bridge local attempt: free fleet on fail, then T3 if configured.

    W2-P1: stamp path=proxy_8091 (or routing.path) and write provenance on failover.
    W3-P2: hop order from router_backend_policy.pick_backend (local->free->grok).
    Prefer free before Grok when prefer_free_before_grok is true.
    """
    path_stamp = str(routing.get("path") or "proxy_8091")

    # Central hop policy (never invent order per call site)
    decision = None
    try:
        from router_backend_policy import pick_backend

        decision = pick_backend(
            prompt=prompt or "",
            task_type=routing.get("task_type"),
            routing=routing,
            local_available=bool(local_result.get("success")),
            skip_local_reason=(
                str(routing.get("local_fail_reason") or "local_failed")
                if not local_result.get("success")
                else (
                    "circuit_8090_open"
                    if routing.get("circuit_8090") in (True, "open", "OPEN")
                    else None
                )
            ),
            prefer_free_before_grok=bool(fleet_policy().get("prefer_free_before_grok", True)),
            force_tier=routing.get("escalation_tier"),
        )
        if hasattr(decision, "to_dict"):
            routing = dict(routing)
            routing["backend_policy"] = decision.to_dict()
    except Exception:
        decision = None

    if local_result.get("success"):
        prov = local_result.setdefault("provenance", {})
        prov.setdefault("path", path_stamp)
        if decision is not None and hasattr(decision, "to_dict"):
            prov.setdefault("backend_policy", decision.to_dict())
            prov.setdefault("selected_backend", "local")
            prov.setdefault("tier_bucket", "local")
        if prov.get("context_augment"):
            return local_result
        return local_result

    hop = list(DEFAULT_HOP if decision is None else (decision.hop_order or DEFAULT_HOP))
    # If pick_backend skipped free (RP/adult), do not fleet
    blocked_free = None
    if decision is not None:
        blocked_free = getattr(decision, "blocked_free_reason", None)

    ok, block_reason, fleet_prompt, mask_map = _prepare_fleet_prompt(prompt, routing)
    if blocked_free:
        ok = False
        block_reason = blocked_free
    if not ok:
        local_result.setdefault("provenance", {})["fleet_escalation_blocked"] = block_reason
        local_result.setdefault("provenance", {})["path"] = path_stamp
        if decision is not None and hasattr(decision, "to_dict"):
            local_result.setdefault("provenance", {})["backend_policy"] = decision.to_dict()
        return local_result

    pol = fleet_policy()
    tier = str(routing.get("escalation_tier") or "")
    hop_first = hop[0] if hop else ""
    brains_first = hop_first == BACKEND_GROK or tier == "T3"
    want_free = BACKEND_FREE in hop and (
        (not brains_first) and pol.get("prefer_free_before_grok", True)
    )
    want_grok = BACKEND_GROK in hop or brains_first

    # Public brains: Grok first even after local miss. Grunt: free first.
    if brains_first and want_grok:
        t3 = try_t3_paid_dispatch(prompt, {**routing, "escalation_tier": "T3"})
        try:
            t3.setdefault("provenance", {})["path"] = path_stamp
            t3.setdefault("provenance", {})["failover"] = "brains_first_t3"
            t3.setdefault("provenance", {})["selected_backend"] = "grok"
            t3.setdefault("provenance", {})["tier_bucket"] = "grok"
            if decision is not None and hasattr(decision, "to_dict"):
                t3.setdefault("provenance", {})["backend_policy"] = decision.to_dict()
        except Exception:
            pass
        if t3.get("success"):
            _append_provenance(
                {
                    "event": "brains_first_t3",
                    "path": path_stamp,
                    "success": True,
                    "tier": t3.get("tier"),
                    "tier_bucket": "grok",
                    "selected_backend": "grok",
                }
            )
            return t3
        if BACKEND_FREE in hop and fleet_routing_enabled():
            t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=True)
            if t2.get("success"):
                prov = t2.setdefault("provenance", {})
                prov["path"] = path_stamp
                prov["failover"] = "brains_t3_miss_to_free"
                prov["selected_backend"] = "free"
                prov["tier_bucket"] = "free"
                return t2
        return t3

    # Free fleet first on local fail (prefer_free_before_grok).
    # Pass original prompt so try_t2 owns mask_map + rehydrate.
    if want_free and fleet_routing_enabled():
        t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=True)
        if t2.get("success"):
            prov = t2.setdefault("provenance", {})
            prov["path"] = path_stamp
            prov["failover"] = "local_fail_to_free_fleet"
            prov["selected_backend"] = "free"
            prov["tier_bucket"] = "free"
            if decision is not None and hasattr(decision, "to_dict"):
                prov["backend_policy"] = decision.to_dict()
            if routing.get("circuit_8090") is not None:
                prov["circuit_8090"] = routing.get("circuit_8090")
            if routing.get("local_fail_reason"):
                prov["local_fail_reason"] = routing.get("local_fail_reason")
            _append_provenance(
                {
                    "event": "local_fail_to_free_fleet",
                    "path": path_stamp,
                    "provider_id": t2.get("provider_id") or prov.get("provider_id"),
                    "model": t2.get("model"),
                    "tier": t2.get("tier"),
                    "tier_bucket": "free",
                    "selected_backend": "free",
                    "role": getattr(decision, "role", None) if decision is not None else None,
                    "circuit_8090": routing.get("circuit_8090"),
                    "local_fail_reason": str(routing.get("local_fail_reason") or "")[:300],
                }
            )
            return t2
        _append_provenance(
            {
                "event": "local_fail_free_fleet_miss",
                "path": path_stamp,
                "error": str((t2 or {}).get("error") or "")[:300],
                "circuit_8090": routing.get("circuit_8090"),
                "tier_bucket": "free",
            }
        )
    elif fleet_routing_enabled() and BACKEND_FREE in hop:
        t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=True)
        if t2.get("success"):
            t2.setdefault("provenance", {})["path"] = path_stamp
            t2.setdefault("provenance", {})["tier_bucket"] = "free"
            return t2

    if want_grok and (tier == "T3" or brains_first):
        t3 = try_t3_paid_dispatch(prompt, {**routing, "escalation_tier": "T3"})
        try:
            t3.setdefault("provenance", {})["path"] = path_stamp
            t3.setdefault("provenance", {})["failover"] = "local_fail_to_t3_after_free"
            t3.setdefault("provenance", {})["selected_backend"] = "grok"
            t3.setdefault("provenance", {})["tier_bucket"] = "grok"
            if decision is not None and hasattr(decision, "to_dict"):
                t3.setdefault("provenance", {})["backend_policy"] = decision.to_dict()
        except Exception:
            pass
        _append_provenance(
            {
                "event": "local_fail_to_t3",
                "path": path_stamp,
                "success": bool(t3.get("success")),
                "tier": t3.get("tier"),
                "tier_bucket": "grok",
                "selected_backend": "grok",
            }
        )
        return t3

    if tier == "T2" and fleet_routing_enabled() and BACKEND_FREE in hop:
        t2 = try_t2_fleet_dispatch(fleet_prompt, routing, local_failed=False)
        if t2.get("success"):
            t2.setdefault("provenance", {})["path"] = path_stamp
            t2.setdefault("provenance", {})["tier_bucket"] = "free"
            return t2

    local_result.setdefault("provenance", {})["path"] = path_stamp
    if decision is not None and hasattr(decision, "to_dict"):
        local_result.setdefault("provenance", {})["backend_policy"] = decision.to_dict()
    return local_result

