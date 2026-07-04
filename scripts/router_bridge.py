#!/usr/bin/env python3
"""
Phronesis Router Bridge — unified local-first dispatch.

Priority order (local-first, opportunistic second, paid Grok last):
  1. PhronesisVault sovereign_router → Local MoE (8090 LRU)
  2. HermesData Ollama router (fallback)
  3. Tier 1.5 Opportunistic Fleet (free APIs via fleet_registry.yaml)
  4. Paid Grok escalation signal — high-stakes / explicit only

Usage:
    from router_bridge import bridge_dispatch
    result = bridge_dispatch("Explain X", task_type="reason", platform="discord")
"""

from __future__ import annotations

# === Tier routing policies (2026-06-27) ===
# Tier 1:   Local MoE (8090 LRU)
# Tier 1.5: Opportunistic Fleet (free APIs) — external_fleet_manager
# Tier 2:   Paid Grok — high-stakes explicit escalation only

FLEET_TRIGGERS = frozenset({
    "latest_external_knowledge",
    "massive_context_window",
    "heavy_tool_chaining",
    "local_dispatch_failed",
    "local_cold_timeout",
    "realtime_search",
})

PAID_GROK_TRIGGERS = frozenset({
    "high_stakes_verification",
    "vision_multimodal",
    "complex_architectural_reasoning",
    "explicit_grok_request",
})


def detect_opportunistic_fleet_triggers(
    prompt: str,
    task_type: str = None,
    context_tokens_estimate: int = None,
    modality: str = None,
    tool_depth: int = None,
    local_failed: bool = False,
) -> dict:
    """Tier 1.5 — free compute/context when local is insufficient but not high-stakes."""
    prompt_lower = (prompt or "").lower()
    matched = []
    reasons = []

    realtime_intent = [
        "breaking news", "current events", "real-time", "live news",
        "latest news", "what happened today", "requires internet", "web search",
        "search for", "look up",
    ]
    if any(k in prompt_lower for k in realtime_intent):
        matched.append("latest_external_knowledge")
        reasons.append("real-time or external context needed")

    ctx = context_tokens_estimate or (len(prompt) // 4 + 8000)
    if ctx > 32000:
        matched.append("massive_context_window")
        reasons.append(f"context ~{ctx} tokens exceeds local comfort")

    if (tool_depth or 0) > 6:
        matched.append("heavy_tool_chaining")
        reasons.append(f"tool depth ~{tool_depth}")

    if local_failed:
        matched.append("local_dispatch_failed")
        reasons.append("local MoE dispatch failed")

    if any(k in prompt_lower for k in ("70b", "large model", "heavy reasoning")):
        matched.append("heavy_reasoning")
        reasons.append("heavy reasoning beyond local hot tier")

    should = bool(matched)
    return {
        "should_route": should,
        "matched_triggers": matched,
        "reason": "; ".join(reasons) if reasons else "no fleet triggers",
        "recommended_tier": "opportunistic_fleet" if should else None,
        "policy_version": "v0.1",
    }


# === Grok-Escalation-Policy v0.2 — Paid tier only ===
def detect_grok_escalation_triggers(
    prompt: str,
    task_type: str = None,
    context_tokens_estimate: int = None,
    modality: str = None,          # 'text', 'vision', 'multimodal'
    tool_depth: int = None,        # number of planned/sequential tool calls
    explicit_flag: bool = False,
    tool_fail_count: int = 0,
) -> dict:
    """
    Returns {
        'should_escalate': bool,
        'matched_triggers': list[str],
        'reason': str,
        'recommended_tier': 'grok_escalation' or None
    }
    """
    prompt_lower = (prompt or '').lower()
    task_lower = (task_type or '').lower().replace('-', '_')
    is_roleplay = task_lower in (
        'roleplay', 'narrative', 'immersive_roleplay', 'dnd', 'd_and_d', 'rp',
    )
    matched = []
    reasons = []

    # Private RP sandboxes stay on local Qwythos — never Grok-escalate on tool noise.
    if is_roleplay:
        return {
            'should_escalate': False,
            'matched_triggers': [],
            'reason': 'roleplay sandbox — local sovereign only',
            'recommended_tier': None,
            'policy_version': 'v0.4_t2_t3',
            'tool_fail_count': int(tool_fail_count or 0),
        }

    # 1. Complex architectural / systems reasoning
    arch_keywords = ['architecture', 'system design', 'multi-hour', 'cross-document', 'novel design', 'high-level design', 'deep synthesis']
    if any(k in prompt_lower for k in arch_keywords) or 'architectural' in task_lower:
        matched.append('complex_architectural_reasoning')
        reasons.append('deep architectural / systems reasoning detected')

    # 2. Vision / multimodal
    vision_keywords = ['image', 'pdf', 'diagram', 'screenshot', 'video', 'visual', 'multimodal', 'analyze image']
    if modality in ('vision', 'multimodal') or any(k in prompt_lower for k in vision_keywords):
        matched.append('vision_multimodal')
        reasons.append('vision or multimodal content detected')

    # 3. Massive context windows
    ctx = context_tokens_estimate or (len(prompt) // 4 + 8000)  # rough with history
    if ctx > 32000:
        matched.append('massive_context_window')
        reasons.append(f'estimated context {ctx} tokens exceeds local comfortable limit')

    # 4. Real-time / external → Tier 1.5 Opportunistic Fleet (NOT paid Grok)
    # (handled by detect_opportunistic_fleet_triggers)

    # 5. High-stakes verification / safety — PAID GROK ONLY
    high_stakes = ['legal', 'financial', 'medical', 'safety-critical', 'high-stakes', 'compliance']
    if explicit_flag or any(k in prompt_lower for k in high_stakes) or 'verify' in task_lower and 'critical' in prompt_lower:
        matched.append('high_stakes_verification')
        reasons.append('high-stakes or safety-critical task')

    # 6. Heavy tool chaining → Tier 1.5 unless explicit grok flag
    # (moderate depth routed to fleet first)

    if explicit_flag:
        matched.append('explicit_grok_request')
        reasons.append('explicit paid Grok escalation requested')

    # T2 — Grok 4.20 Heavy: repeated local tool failures or explicit heavy reasoning
    heavy_reasoning = any(
        k in prompt_lower
        for k in ('heavy reasoning', 'grok heavy', 'tier 2', 't2 escalate', 'deep reasoning')
    )
    if heavy_reasoning or explicit_flag:
        matched.append('heavy_reasoning')
        reasons.append('explicit heavy-reasoning / T2 request')
    fails = int(tool_fail_count or 0)
    image_timeout = any(
        k in prompt_lower
        for k in ('image_gen_timeout', 'image timeout', 'comfy timeout', 'generation timed out')
    )
    multi_tool = int(tool_depth or 0) >= 3
    if fails > 1:
        matched.append('tool_fail_threshold')
        reasons.append(f'tool_fail_count={fails} exceeds T1 tolerance')
    if image_timeout:
        matched.append('image_gen_timeout')
        reasons.append('image generation timeout - escalate for tool recovery')
    if multi_tool:
        matched.append('multi_tool_chain')
        reasons.append(f'tool_depth={tool_depth} multi-step chain')

    should = bool(matched)
    tier = None
    if should:
        if fails > 2 or image_timeout or multi_tool:
            tier = 'T3_grok_heavy'
        elif fails > 1 or heavy_reasoning:
            tier = 'T2_grok_heavy'
        else:
            tier = 'grok_escalation'
    return {
        'should_escalate': should,
        'matched_triggers': matched,
        'reason': '; '.join(reasons) if reasons else 'no grok triggers matched',
        'recommended_tier': tier,
        'policy_version': 'v0.4_t2_t3',
        'tool_fail_count': fails,
    }

import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

HERMES_SCRIPTS = Path(__file__).resolve().parent
VAULT_SCRIPTS = Path("D:/PhronesisVault/scripts")
HERMES_ROUTER_PATH = HERMES_SCRIPTS / "sovereign_router.py"
VAULT_ROUTER_PATH = VAULT_SCRIPTS / "sovereign_router.py"
INVENTORY_PATH = VAULT_SCRIPTS / "model_inventory.py"
MOE_MAP_PATH = Path("D:/PhronesisVault/Operations/MoE-Task-Type-Map-v0.1.json")

HIGH_FIDELITY_TIERS = frozenset({"local_warm", "local_cold"})


def _load_module(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_up() -> bool:
    return _port_open("127.0.0.1", 11434)


def _unified_router_up() -> bool:
    return _port_open("127.0.0.1", 8090)


def _legacy_moe_up() -> bool:
    return _port_open("127.0.0.1", 8081) and (
        _port_open("127.0.0.1", 8082) or _port_open("127.0.0.1", 8083)
    )


def _llama_tiers_up() -> bool:
    return _unified_router_up() or any(_port_open("127.0.0.1", p) for p in (8081, 8082, 8083))


def _moe_production_ready() -> bool:
    if _unified_router_up():
        try:
            cfg = _load_moe_task_map().get("unified_router") or {}
            if cfg.get("enabled") is not False:
                return True
        except Exception:
            return True
    return _legacy_moe_up()


def _port_matrix() -> Dict[str, bool]:
    return {
        "11434": _port_open("127.0.0.1", 11434),
        "8081": _port_open("127.0.0.1", 8081),
        "8082": _port_open("127.0.0.1", 8082),
        "8083": _port_open("127.0.0.1", 8083),
        "8090": _port_open("127.0.0.1", 8090),
        "8091": _port_open("127.0.0.1", 8091),
    }


def _load_moe_task_map() -> Dict[str, Any]:
    try:
        if MOE_MAP_PATH.exists():
            return json.loads(MOE_MAP_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def preview_route(task_type: Optional[str] = None, prompt: str = "") -> Dict[str, Any]:
    """
    Resolve MoE tier/port from task_type + prompt without dispatching.
    Used by sovereign_openai_proxy for tier-aware context trimming + LRU preload hints.
    """
    unified_cfg = _load_moe_task_map().get("unified_router") or {}
    unified_enabled = bool(unified_cfg.get("enabled")) and _unified_router_up()
    tier_models = unified_cfg.get("tier_logical_models") or {}

    entry = _resolve_task_type_entry(task_type, prompt)
    if entry:
        tier = str(entry.get("tier") or "local_warm")
        port = int(unified_cfg.get("port") or 8090) if unified_enabled else entry.get("port")
        logical = tier_models.get(tier)
        return {
            "task_type": entry.get("task_type"),
            "tier": tier,
            "port": port,
            "logical_model": logical,
            "unified_router": unified_enabled,
            "complexity": entry.get("complexity"),
            "map_entry": entry,
            "inferred": False,
        }
    tier = "local_hot"
    port = int(unified_cfg.get("port") or 8090) if unified_enabled else 8081
    return {
        "task_type": task_type,
        "tier": tier,
        "port": port,
        "logical_model": tier_models.get(tier) if unified_enabled else None,
        "unified_router": unified_enabled,
        "complexity": _complexity_from_task_type(task_type, prompt),
        "map_entry": None,
        "inferred": True,
        "notes": "no MoE map match — conservative hot-tier trim budget",
    }


def _resolve_task_type_entry(task_type: Optional[str], prompt: str = "") -> Optional[Dict[str, Any]]:
    data = _load_moe_task_map()
    types = data.get("task_types") or {}
    aliases = data.get("aliases") or {}
    key = (task_type or "").strip().lower().replace("-", "_")
    if not key or key in ("auto", "default", "none"):
        # Holistic infer from prompt
        p = (prompt or "").lower()
        if any(k in p for k in ("classify", "tag only", "reply only: simple")):
            key = "classify"
        elif any(k in p for k in ("def ", "import ", "python", "refactor")):
            key = "code"
        elif any(k in p for k in ("growth blueprint", "distill", "summariz", "synthesis", "moc")):
            key = "synthesis"
        elif any(
            k in p
            for k in (
                "roleplay_mode:", "uncensored_roleplay:", "[platform: alice-roleplay]",
                "/rp ", "/roleplay",
            )
        ):
            key = "roleplay"
        else:
            return None
    if key in aliases:
        key = aliases[key]
    entry = types.get(key)
    if isinstance(entry, dict):
        return {"task_type": key, **entry}
    return None


def _complexity_from_task_type(task_type: Optional[str], prompt: str = "") -> str:
    entry = _resolve_task_type_entry(task_type, prompt)
    if entry and entry.get("complexity"):
        return str(entry["complexity"])
    simple_types = ("simple", "chat", "fast", "lookup", "classify", "tag", "metadata_extraction")
    if (task_type or "").lower().replace("-", "_") in simple_types:
        return "simple"
    return "complex"


def _attach_quality_warning(result: Dict[str, Any]) -> Dict[str, Any]:
    """Surface silent degradation when high-fidelity tier fell back to 8081 hot."""
    prov = result.setdefault("provenance", {})
    raw = result.get("raw") or {}
    decision = (raw.get("route") or {}).get("decision") or {}
    if decision.get("quality_warning"):
        prov["quality_warning"] = decision["quality_warning"]
        result["quality_warning"] = decision["quality_warning"]
        return result
    if decision.get("tier_fallback"):
        orig = decision.get("original_escalation_tier") or decision.get("escalation_tier")
        actual = decision.get("escalation_tier")
        if orig in HIGH_FIDELITY_TIERS and actual == "local_hot":
            warn = "degraded - tier_fallback to 8081"
            prov["quality_warning"] = warn
            prov["tier_fallback"] = True
            prov["original_escalation_tier"] = orig
            result["quality_warning"] = warn
    return result


def _inventory_hint(complexity: str) -> Optional[Dict[str, Any]]:
    try:
        inv = _load_module("phronesis_model_inventory", INVENTORY_PATH)
        return inv.select_best_local_model("complex" if complexity != "simple" else "simple")
    except Exception:
        return None


def _dispatch_ollama(prompt: str, task_type: Optional[str], force_local: bool) -> Dict[str, Any]:
    ollama_router = _load_module("hermes_ollama_router", HERMES_ROUTER_PATH)
    return ollama_router.dispatch(prompt, task_type=task_type, force_local=force_local)


def _dispatch_vault(
    prompt: str,
    task_type: Optional[str],
    platform: str,
    role: str,
    *,
    force_roleplay: bool = False,
) -> Dict[str, Any]:
    if str(VAULT_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(VAULT_SCRIPTS))
    vault_router = _load_module("phronesis_vault_router", VAULT_ROUTER_PATH)
    router = vault_router.SovereignRouter()
    effective_task_type = "roleplay" if force_roleplay else task_type
    if (effective_task_type or "").lower().replace("-", "_") == "roleplay":
        effective_task_type = "roleplay"

    def _vault_round(tt: Optional[str]) -> Dict[str, Any]:
        routed = router.route(
            role=role or "default",
            task=prompt,
            platform=platform or "phronesis_bridge",
            task_type=tt,
        )
        if routed.get("status") == "blocked":
            return {
                "success": False,
                "provenance": {"source": "vault_sovereign_router_v0.11", "blocked": routed.get("reason")},
            }
        decision = routed.get("decision") or {}
        if tt == "roleplay":
            rocinante = getattr(vault_router, "logical_model_for_tier", None)
            if callable(rocinante):
                rocinante_id = rocinante("local_roleplay")
            else:
                rocinante_id = "rocinante-12b"
            decision["task_type"] = "roleplay"
            decision["escalation_tier"] = "local_roleplay"
            decision["model"] = rocinante_id
            decision["resolved_llama_model"] = rocinante_id
            decision["logical_model"] = rocinante_id
        dispatched = router.dispatch(decision, prompt, "")
        text = (dispatched.get("response") or dispatched.get("text") or "").strip()
        ok = bool(text) and dispatched.get("status") not in ("error", "failed")
        tier = str(
            dispatched.get("escalation_tier")
            or decision.get("escalation_tier")
            or ""
        )
        resolved = (
            dispatched.get("resolved_model")
            or decision.get("resolved_llama_model")
            or decision.get("model")
        )
        prov = {
            "source": "vault_sovereign_router_v0.11",
            "backend": decision.get("backend"),
            "platform": platform,
            "port_hint": decision.get("port_hint"),
            "inventory_hint": decision.get("inventory_hint"),
            "collaboration_mode": routed.get("collaboration_mode"),
            "task_type": tt or decision.get("task_type"),
            "task_type_map": decision.get("task_type_map"),
            "tier_fallback": decision.get("tier_fallback"),
            "original_escalation_tier": decision.get("original_escalation_tier"),
            "resolved_model": resolved,
        }
        if decision.get("quality_warning"):
            prov["quality_warning"] = decision["quality_warning"]
        return {
            "response": text or json.dumps({"routed": routed.get("status"), "tier": tier})[:500],
            "model": resolved,
            "tier": tier,
            "provenance": prov,
            "success": ok,
            "raw": {"route": routed, "dispatch": dispatched},
            "quality_warning": decision.get("quality_warning"),
        }

    out = _vault_round(effective_task_type)
    if not out.get("success"):
        return out

    try:
        from roleplay_subsystem import is_refusal_response
    except Exception:
        is_refusal_response = None  # type: ignore

    tier = str(out.get("tier") or "")
    text = str(out.get("response") or "")
    wrong_tier = tier != "local_roleplay" and "rocinante" not in str(out.get("model") or "").lower()
    refusal = bool(is_refusal_response and is_refusal_response(text))
    if (force_roleplay or effective_task_type == "roleplay") and (wrong_tier or refusal):
        retry = _vault_round("roleplay")
        retry_prov = retry.setdefault("provenance", {})
        retry_prov["refusal_retry"] = True
        retry_prov["refusal_retry_reason"] = "wrong_tier" if wrong_tier else "aligned_refusal"
        retry_prov["original_tier"] = tier
        retry_prov["original_model"] = out.get("model")
        if retry.get("success"):
            return retry
        out.setdefault("provenance", {})["refusal_retry_failed"] = True
    return out


def bridge_dispatch(
    prompt: str,
    task_type: Optional[str] = None,
    platform: str = "",
    role: str = "default",
    force_local: bool = True,
    prefer: str = "auto",
    context_tokens_estimate: int = None,
    modality: str = None,
    tool_depth: int = None,
    explicit_grok_flag: bool = False,
    tool_fail_count: int = 0,
    memory_scope: str = "",
    chat_id: str = "",
    thread_id: str = "",
    parent_channel_id: str = "",
) -> Dict[str, Any]:
    """
    Unified entry for Phronesis local-first routing.

    prefer: auto | ollama | vault
    """
    started = time.time()

    try:
        from sovereign_memory_manager import make_memory_scope

        if not memory_scope:
            memory_scope = make_memory_scope(
                platform or "roleplay",
                chat_id=chat_id,
                thread_id=thread_id,
                parent_channel_id=parent_channel_id,
            )
    except Exception:
        memory_scope = memory_scope or platform or "roleplay"

    _mem_ckpt = {
        "memory_scope": memory_scope,
        "chat_id": chat_id,
        "thread_id": thread_id,
        "parent_channel_id": parent_channel_id,
    }

    map_entry = _resolve_task_type_entry(task_type, prompt)
    complexity = _complexity_from_task_type(task_type, prompt)
    inventory = _inventory_hint(complexity)

    fleet_info = detect_opportunistic_fleet_triggers(
        prompt=prompt,
        task_type=task_type,
        context_tokens_estimate=context_tokens_estimate,
        modality=modality,
        tool_depth=tool_depth,
    )
    escalation_info = detect_grok_escalation_triggers(
        prompt=prompt,
        task_type=task_type,
        context_tokens_estimate=context_tokens_estimate,
        modality=modality,
        tool_depth=tool_depth,
        explicit_flag=explicit_grok_flag,
        tool_fail_count=int(tool_fail_count or 0),
    )

    provenance: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "force_local": force_local,
        "platform": platform or None,
        "task_type": task_type,
        "ollama_up": _ollama_up(),
        "llama_tiers_up": _llama_tiers_up(),
        "inventory_hint": inventory,
        "bridge": "router_bridge_v3",
        "opportunistic_fleet_policy": fleet_info,
        "grok_escalation_policy": escalation_info,
        "moe_task_type_map": map_entry,
    }
    provenance["unified_generalist"] = True

    # Paid Grok (Tier 2) — never block force_local sovereign dispatch (log only).
    if escalation_info.get("should_escalate") and not force_local:
        provenance["escalation_recommended"] = True
        provenance["escalation_triggers"] = escalation_info["matched_triggers"]
        provenance["escalation_reason"] = escalation_info["reason"]
        # Return structured escalation signal (local router will prepare stub)
        return {
            "response": "[ESCALATION] Grok handoff recommended per policy v0.1",
            "model": None,
            "tier": "grok_escalation",
            "success": True,
            "escalation": True,
            "provenance": provenance,
            "handoff_payload": {
                "compressed_stub": True,
                "retrieved_package": True,
            }
        }

    attempts = []

    def _try_ollama() -> Optional[Dict[str, Any]]:
        if not _ollama_up():
            attempts.append({"backend": "ollama", "status": "skipped", "reason": "port 11434 down"})
            return None
        res = _dispatch_ollama(prompt, task_type, force_local)
        attempts.append({"backend": "ollama", "status": "ok" if res.get("success") else "fail"})
        if res.get("success"):
            res["provenance"] = {**provenance, **res.get("provenance", {}), "selected_backend": "ollama"}
            res["attempts"] = attempts
            res["latency_sec"] = round(time.time() - started, 2)
            _record_local_moe_telemetry(res, started=started, backend="ollama", port=11434)
            _nanodb_record_dispatch(res, "ollama", task_type)
            return res
        res["latency_sec"] = round(time.time() - started, 2)
        _record_local_moe_telemetry(res, started=started, backend="ollama", port=11434)
        _nanodb_record_dispatch(res, "ollama", task_type)
        return None

    def _try_vault() -> Optional[Dict[str, Any]]:
        if not _llama_tiers_up():
            attempts.append({"backend": "vault", "status": "skipped", "reason": "no 808x/8090 listeners"})
            return None
        # Preload LRU slots before vault dispatch when unified router is active
        if _unified_router_up():
            try:
                route_preview = preview_route(task_type, prompt)
                from lru_router_manager import preload_from_route_preview
                preload_from_route_preview(route_preview)
            except Exception:
                pass
        try:
            force_rp = (task_type or "").lower().replace("-", "_") == "roleplay"
            res = _dispatch_vault(
                prompt, task_type, platform, role, force_roleplay=force_rp,
            )
            attempts.append({"backend": "vault", "status": "ok" if res.get("success") else "fail"})
            if res.get("success"):
                res["provenance"] = {**provenance, **res.get("provenance", {}), "selected_backend": "vault_v0.11"}
                res["attempts"] = attempts
                res["latency_sec"] = round(time.time() - started, 2)
                out = _attach_quality_warning(res)
                port = 8090 if _unified_router_up() else int((out.get("provenance") or {}).get("port_hint") or 8090)
                _record_local_moe_telemetry(out, started=started, backend="vault", port=port)
                _nanodb_record_dispatch(out, "vault", task_type)
                return out
            res["latency_sec"] = round(time.time() - started, 2)
            _record_local_moe_telemetry(res, started=started, backend="vault", port=8090 if _unified_router_up() else 8081)
            _nanodb_record_dispatch(res, "vault", task_type)
        except Exception as exc:
            attempts.append({"backend": "vault", "status": "error", "error": str(exc)})
            _record_local_moe_telemetry(
                {"success": False, "latency_sec": round(time.time() - started, 2), "error": str(exc)},
                started=started,
                backend="vault",
                port=8090 if _unified_router_up() else 8081,
            )
        return None

    def _try_fleet(*, local_failed: bool = False) -> Optional[Dict[str, Any]]:
        fleet_triggers = detect_opportunistic_fleet_triggers(
            prompt=prompt,
            task_type=task_type,
            context_tokens_estimate=context_tokens_estimate,
            tool_depth=tool_depth,
            local_failed=local_failed,
        )
        if not fleet_triggers.get("should_route") and not local_failed:
            attempts.append({"backend": "opportunistic_fleet", "status": "skipped", "reason": "no triggers"})
            return None
        try:
            from external_fleet_manager import FleetManager, fleet_available

            if not fleet_available():
                attempts.append({"backend": "opportunistic_fleet", "status": "skipped", "reason": "no providers"})
                return None
            fm = FleetManager()
            include_ctx = "latest_external_knowledge" in (fleet_triggers.get("matched_triggers") or [])
            res = fm.dispatch_opportunistic(
                prompt,
                task_type=task_type,
                triggers=fleet_triggers.get("matched_triggers"),
                include_context=include_ctx,
            )
            attempts.append({"backend": "opportunistic_fleet", "status": "ok" if res.get("success") else "fail"})
            if res.get("success"):
                out = {
                    "response": res.get("response", ""),
                    "model": res.get("model"),
                    "tier": "opportunistic_fleet",
                    "success": True,
                    "provenance": {
                        **provenance,
                        "selected_backend": "opportunistic_fleet",
                        "provider_id": res.get("provider_id"),
                        "provider_name": res.get("provider_name"),
                        "fleet_triggers": fleet_triggers.get("matched_triggers"),
                        "context_prefetch": res.get("context_prefetch"),
                    },
                    "attempts": attempts,
                    "latency_sec": res.get("latency_sec"),
                    "tokens_saved_estimate": "high (free fleet, not paid Grok)",
                }
                _log_token_usage(prompt, out, platform, task_type)
                _nanodb_record_dispatch(out, "fleet", task_type)
                return out
        except Exception as exc:
            attempts.append({"backend": "opportunistic_fleet", "status": "error", "error": str(exc)})
        return None

    order = []
    if prefer == "ollama":
        order = [_try_ollama, _try_vault]
    elif prefer == "vault":
        order = [_try_vault, _try_ollama]
    else:
        # Prefer vault MoE tiers when llama.cpp is up (sovereign GGUF path)
        order = [_try_vault, _try_ollama] if _llama_tiers_up() else [_try_ollama, _try_vault]

    for fn in order:
        hit = fn()
        if hit:
            hit.setdefault("tokens_saved_estimate", "high (local bridge, no paid Grok)")
            _log_token_usage(prompt, hit, platform, task_type)
            _checkpoint_bridge_dispatch(
                prompt, platform, task_type, tool_depth, hit, **_mem_ckpt,
            )
            return hit

    # Tier 1.5 — opportunistic fleet after local miss (never for uncensored roleplay)
    fleet_hit = _try_fleet(local_failed=True)
    if fleet_hit:
        _checkpoint_bridge_dispatch(
            prompt, platform, task_type, tool_depth, fleet_hit, **_mem_ckpt,
        )
        return fleet_hit

    # Tier 1.5 — proactive fleet if triggers matched (local may have been skipped)
    if fleet_info.get("should_route"):
        fleet_hit = _try_fleet(local_failed=False)
        if fleet_hit:
            _checkpoint_bridge_dispatch(
                prompt, platform, task_type, tool_depth, fleet_hit, **_mem_ckpt,
            )
            return fleet_hit

    fail = {
        "response": "[ROUTER BRIDGE] Local + Opportunistic Fleet unavailable. Paid Grok not auto-invoked.",
        "model": None,
        "tier": None,
        "success": False,
        "provenance": provenance,
        "attempts": attempts,
        "latency_sec": round(time.time() - started, 2),
        "tokens_saved_estimate": "n/a (dispatch failed)",
    }
    _log_token_usage(prompt, fail, platform, task_type)
    return fail


def _telemetry_monitor():
    try:
        from sovereign_telemetry_monitor import get_telemetry_monitor
        return get_telemetry_monitor()
    except Exception:
        return None


def _checkpoint_bridge_dispatch(
    prompt: str,
    platform: str,
    task_type: Optional[str],
    tool_depth: Optional[int],
    result: Dict[str, Any],
    *,
    memory_scope: str = "",
    chat_id: str = "",
    thread_id: str = "",
    parent_channel_id: str = "",
) -> None:
    """Persist working + procedural state after successful bridge dispatch."""
    if not result.get("success"):
        return
    try:
        from sovereign_memory_manager import get_memory_manager

        mgr = get_memory_manager()
        plat = platform or "router_bridge"
        sid = mgr.ensure_active_session(plat)
        working: list = []
        if prompt:
            working.append({"role": "user", "content": prompt[:8000]})
        resp = str(result.get("response") or "")
        if resp:
            working.append({"role": "assistant", "content": resp[:8000]})
        is_roleplay = (task_type or "").lower().replace("-", "_") in (
            "roleplay", "narrative", "dnd", "d_and_d", "immersive_roleplay",
        )
        if is_roleplay:
            from sovereign_memory_manager import checkpoint_roleplay_turn

            checkpoint_roleplay_turn(
                platform=plat,
                user_content=prompt[:8000],
                assistant_content=resp[:8000],
                campaign=task_type or "roleplay",
                memory_scope=memory_scope,
                chat_id=chat_id,
                thread_id=thread_id,
                parent_channel_id=parent_channel_id,
            )
            return
        procedural = {
            "active_task": task_type or "auto",
            "last_tier": result.get("tier"),
            "last_model": result.get("model"),
            "tool_depth": tool_depth or 0,
            "pending_delegations": [],
            "platform": plat,
            "last_dispatch_success": True,
        }
        mgr.checkpoint(
            session_id=sid,
            working_memory=working,
            procedural_state=procedural,
            metadata={"source": "router_bridge"},
        )
    except Exception:
        pass


def _nanodb_record_dispatch(result: Dict[str, Any], backend: str, task_type: str = None) -> None:
    """Append dispatch metrics to nanodb (JSON-backed nanoscale DB)."""
    try:
        import nanodb as ndb
        model = str(result.get("model") or "")
        latency_ms = float(result.get("latency_sec", 0)) * 1000
        # Estimate TPS from response token count if available
        tps = 0.0
        tokens = 0
        resp_text = str(result.get("response") or "")
        if resp_text and latency_ms > 0:
            # rough estimate: ~4 chars per token, tokens / seconds
            tokens = len(resp_text) // 4
            tps = tokens / (latency_ms / 1000) if latency_ms > 0 else 0
        ndb.record_dispatch(
            task_type=task_type or "auto",
            model=model,
            latency_ms=round(latency_ms, 1),
            tps=round(tps, 1),
        )
    except Exception:
        pass


def _record_local_moe_telemetry(
    result: Dict[str, Any],
    *,
    started: float,
    backend: str,
    port: int = 8090,
) -> None:
    """Emit Tier 1 dispatch metrics into unified stress model."""
    tel = _telemetry_monitor()
    if not tel:
        return
    elapsed = float(result.get("latency_sec") or round(time.time() - started, 2))
    success = bool(result.get("success"))
    prov = result.get("provenance") or {}
    port_hint = prov.get("port_hint") or port
    try:
        port_int = int(port_hint) if port_hint else port
    except (TypeError, ValueError):
        port_int = port
    tel.record_local_moe_dispatch(
        success=success,
        latency_sec=elapsed,
        port=port_int,
        backend=backend,
        model=str(result.get("model") or ""),
        timeout=elapsed >= 120 and not success,
        error=None if success else str(result.get("quality_warning") or result.get("error") or "dispatch_fail"),
    )


def _log_token_usage(
    prompt: str,
    result: Dict[str, Any],
    platform: str,
    task_type: Optional[str],
) -> None:
    """Mirror vault sovereign_router token-usage-local.jsonl append."""
    try:
        logp = Path("D:/PhronesisVault/Operations/token-usage-local.jsonl")
        logp.parent.mkdir(parents=True, exist_ok=True)
        backend = (result.get("provenance") or {}).get("selected_backend", "none")
        is_local = bool(result.get("success")) and backend in ("ollama", "vault_v0.11")
        is_fleet = bool(result.get("success")) and backend == "opportunistic_fleet"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "router_bridge",
            "task_preview": (prompt or "")[:120],
            "choice": "local" if is_local else ("opportunistic_fleet" if is_fleet else "failed-local"),
            "model": result.get("model"),
            "platform": platform or None,
            "task_type": task_type,
            "backend": backend,
            "would_be_remote": None if (is_local or is_fleet) else "grok_escalation",
            "est_tokens_saved": 300 if is_local else (200 if is_fleet else 0),
            "success": result.get("success"),
        }
        with open(logp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def assess_local_stack(
    relay_preview: str = "",
    task_type: str = "auto",
    run_classifier_probe: bool = True,
) -> Dict[str, Any]:
    """
    Pre-flight diagnostic for relay / cron — no hermes.exe, no Grok.
    Port matrix + optional 8083 classifier mock + task_type map resolution.
    """
    ports = _port_matrix()
    map_entry = _resolve_task_type_entry(task_type if task_type != "auto" else None, relay_preview)
    if not map_entry and task_type == "auto":
        map_entry = _resolve_task_type_entry(None, relay_preview)

    classifier_probe: Dict[str, Any] = {"skipped": True, "reason": "8083 down"}
    if run_classifier_probe and ports.get("8083"):
        probe_prompt = (
            "Reply ONLY with one word: simple or complex. Task: "
            + (relay_preview[:200] if relay_preview else "Classify this routing health check.")
        )
        try:
            probe = bridge_dispatch(
                probe_prompt,
                task_type="classify",
                platform="assess_local_preflight",
                force_local=True,
                prefer="vault",
                context_tokens_estimate=500,
            )
            classifier_probe = {
                "skipped": False,
                "success": probe.get("success"),
                "tier": probe.get("tier"),
                "model": probe.get("model"),
                "port_hint": (probe.get("provenance") or {}).get("port_hint"),
                "response_preview": (probe.get("response") or "")[:80],
                "quality_warning": probe.get("quality_warning"),
            }
        except Exception as exc:
            classifier_probe = {"skipped": False, "error": str(exc)}

    # Current stack: 8091 (phronesis-sovereign) is the active proxy
    # Old MoE ports 8081-8083 are phased out
    moe_ready = ports["8091"] or (ports["8081"] and (ports["8082"] or ports["8083"]))
    status = "GREEN" if moe_ready else ("YELLOW" if ports["8081"] else "RED")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "ports": ports,
        "ollama_up": ports["11434"],
        "moe_production_ready": moe_ready,
        "task_type_requested": task_type,
        "task_type_resolved": map_entry,
        "classifier_probe": classifier_probe,
        "relay_preview_chars": len(relay_preview or ""),
        "recommendation": (
            "Local stack ready (phronesis-sovereign or MoE)"
            if moe_ready
            else "Start Start-MoE-Stack.ps1 or phronesis-sovereign before cron/relay"
        ),
    }


def print_assess_local_report(report: Dict[str, Any]) -> None:
    print("=== Phronesis Local Stack Pre-Flight ===")
    print(f"Status: {report.get('status')}")
    print(f"Time:   {report.get('timestamp')}")
    print("")
    print("Port Matrix:")
    for port, up in (report.get("ports") or {}).items():
        mark = "UP" if up else "DOWN"
        print(f"  {port}: {mark}")
    print("")
    resolved = report.get("task_type_resolved")
    if resolved:
        print(f"Task map: {resolved.get('task_type')} -> tier={resolved.get('tier')} port={resolved.get('port')}")
    else:
        print("Task map: (no match — will use keyword heuristics)")
    print("")
    probe = report.get("classifier_probe") or {}
    if probe.get("skipped"):
        print(f"Classifier probe: SKIPPED ({probe.get('reason')})")
    else:
        print(f"Classifier probe: success={probe.get('success')} tier={probe.get('tier')} port={probe.get('port_hint')}")
        if probe.get("response_preview"):
            print(f"  preview: {probe['response_preview']}")
        if probe.get("quality_warning"):
            print(f"  WARN: {probe['quality_warning']}")
    print("")
    print(f"Recommendation: {report.get('recommendation')}")


def self_test() -> Dict[str, Any]:
    print("=== Router Bridge Self-Test ===")
    print(f"Ollama: {_ollama_up()} | Llama tiers: {_llama_tiers_up()}")
    res = bridge_dispatch("What is 2+2? Reply with the number only.", task_type="simple", platform="phronesis_bridge")
    print("Success:", res.get("success"))
    print("Backend:", res.get("provenance", {}).get("selected_backend"))
    print("Model:", res.get("model"))
    print("Preview:", (res.get("response") or "")[:120])
    return res


try:
    from sovereign_memory_manager import hydrate_boot_state as _hydrate_memory_boot

    _hydrate_memory_boot(platform="router_bridge")
except Exception:
    pass


if __name__ == "__main__":
    self_test()
