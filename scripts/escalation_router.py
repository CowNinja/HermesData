#!/usr/bin/env python3
"""
escalation_router.py — T2 (free fleet) + T3 (paid) escalation for sovereign proxy.

Local-first invariant:
  - Qwythos @ :8090 is always attempted first (native passthrough).
  - T2 supplements on: local failure, proactive realtime triggers (context augment),
    or explicit escalation_tier=T2 (tool stress).
  - T3 only on explicit escalation_tier=T3 or high-stakes triggers — never roleplay.

Config gate: local_sovereign.opportunistic_fleet.enabled in config.yaml
Registry: config/fleet_registry.yaml
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
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
    """Merged fleet policy from config.yaml + defaults."""
    raw = _load_yaml(CONFIG_PATH)
    fleet = (raw.get("local_sovereign") or {}).get("opportunistic_fleet") or {}
    return {
        "enabled": bool(fleet.get("enabled")),
        "prefer_free_before_grok": bool(fleet.get("prefer_free_before_grok", True)),
        "augment_local_with_context": bool(fleet.get("augment_local_with_context", True)),
        "fallback_on_local_fail": bool(fleet.get("fallback_on_local_fail", True)),
        "proactive_realtime_triggers": bool(fleet.get("proactive_realtime_triggers", True)),
        "registry": str(fleet.get("registry") or HERMES_ROOT / "config" / "fleet_registry.yaml"),
        "block_roleplay": True,
    }


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


def _fleet_triggers(prompt: str, routing: Dict[str, Any], *, local_failed: bool = False) -> Dict[str, Any]:
    from router_bridge import detect_opportunistic_fleet_triggers

    return detect_opportunistic_fleet_triggers(
        prompt=prompt,
        task_type=routing.get("task_type"),
        context_tokens_estimate=len(prompt) // 4 + 4000,
        local_failed=local_failed,
    )


def maybe_augment_messages_with_context(
    messages: List[Dict[str, Any]],
    prompt: str,
    routing: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    T2 augment mode: prefetch real-time context into messages before local dispatch.
    Does not replace local inference — supplements working memory only.
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
        ctx = fm.dispatch_context(prompt[:600], capabilities=["real-time-search"])
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
                "[T2 CONTEXT AUGMENT — opportunistic fleet prefetch; verify before citing]\n"
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
    """Tier 1.5 — free compute + optional context via external_fleet_manager."""
    started = time.time()
    pol = fleet_policy()
    if not pol.get("enabled"):
        return {"success": False, "tier": "opportunistic_fleet", "error": "fleet_disabled_in_config"}
    if is_roleplay_route(routing):
        return {"success": False, "tier": "opportunistic_fleet", "error": "roleplay_blocked"}

    triggers = _fleet_triggers(prompt, routing, local_failed=local_failed)
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
            prompt,
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
    Tier 3 — paid / heavy reasoning. Tries free fleet first when prefer_free_before_grok.
    Falls back to xAI Grok OpenAI-compat when GROK_API_KEY present.
    """
    if is_roleplay_route(routing):
        return {"success": False, "tier": "paid", "error": "roleplay_blocked"}

    pol = fleet_policy()
    if pol.get("prefer_free_before_grok"):
        t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=True)
        if t2.get("success"):
            prov = t2.setdefault("provenance", {})
            prov["t3_deferred_to_t2"] = True
            return t2

    api_key = os.environ.get("GROK_API_KEY", "").strip()
    model = "grok-4.20-reasoning"
    try:
        raw = _load_yaml(CONFIG_PATH)
        xs = raw.get("x_search") or {}
        if xs.get("model"):
            model = str(xs["model"])
    except Exception:
        pass

    if not api_key:
        return {
            "success": False,
            "escalation": True,
            "tier": "grok_escalation",
            "response": "[T3 PAID ESCALATION] GROK_API_KEY missing — enable in Bitwarden or use Hermes Grok provider directly.",
            "provenance": {
                "selected_backend": "paid_escalation",
                "escalation_tier": "T3",
                "escalation_reason": "paid_key_missing",
            },
        }

    url = "https://api.x.ai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt[:120000]}],
        "max_tokens": 4096,
        "temperature": 0.3,
    }
    started = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "").strip()
        if not content:
            raise RuntimeError("empty T3 response")
        latency = round(time.time() - started, 2)
        _log({"event": "t3_ok", "model": model, "latency_sec": latency})
        return {
            "success": True,
            "response": content,
            "model": model,
            "tier": "paid_grok",
            "latency_sec": latency,
            "provenance": {
                "selected_backend": "paid_grok",
                "escalation_tier": "T3",
                "provider": "xai",
            },
            "openai_response": body,
        }
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        _log({"event": "t3_http_error", "status": exc.code, "body": err_body})
        return {
            "success": False,
            "escalation": True,
            "tier": "grok_escalation",
            "response": f"[T3 PAID ESCALATION] HTTP {exc.code}: {err_body[:200]}",
            "provenance": {"selected_backend": "paid_grok", "escalation_tier": "T3", "http_status": exc.code},
        }
    except Exception as exc:
        _log({"event": "t3_error", "error": str(exc)})
        return {
            "success": False,
            "escalation": True,
            "tier": "grok_escalation",
            "response": f"[T3 PAID ESCALATION] {exc}",
            "provenance": {"selected_backend": "paid_grok", "escalation_tier": "T3", "error": str(exc)},
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

    tier = str(routing.get("escalation_tier") or "")
    if fleet_routing_enabled():
        t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=True)
        if t2.get("success"):
            return t2

    if tier == "T3":
        return try_t3_paid_dispatch(prompt, routing)

    if tier == "T2" and fleet_routing_enabled():
        t2 = try_t2_fleet_dispatch(prompt, routing, local_failed=False)
        if t2.get("success"):
            return t2

    return local_result