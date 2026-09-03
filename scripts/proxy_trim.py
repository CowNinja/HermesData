#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Pure-ish chat trim helpers for the sovereign proxy.

Not a listener. One :8091 process still owns HTTP.
trim_messages_tier_aware lazily imports flatten/log/route from the proxy
so this module can load without a circular import.

Re-exported from sovereign_openai_proxy.py for existing tests.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

SYSTEM_BUDGET_RATIO = 0.15
STUB_MAX_CHARS = 6000
MESSAGE_PREVIEW_CHARS = 180
# Resurrection / long-thread hydrate: original anchor + last 6-8 turns.
SLIDING_TAIL_MESSAGES = 16  # 8 user/assistant pairs
_STALE_SYSTEM_MARKERS = (
    "[RELEVANT ENTITY CONTEXT]",
    "GOLDEN TOOL EXAMPLES",
    "You are now in tool-optimised mode",
    "[TIER-AWARE CONTEXT TRIM",
)


def extract_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif "text" in block:
                    parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


# Proxy-internal alias (flatten and HTTP still use the underscore name).
_extract_content = extract_message_content


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 3)


def message_tokens(msg: Dict[str, Any]) -> int:
    tokens = estimate_tokens(extract_message_content(msg.get("content")))
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        try:
            tokens += estimate_tokens(json.dumps(tool_calls))
        except Exception:
            tokens += 256
    return max(1, tokens)


_message_tokens = message_tokens


def estimate_tools_tokens(tools: Any) -> int:
    if not tools:
        return 0
    try:
        return estimate_tokens(json.dumps(tools))
    except Exception:
        return 4096


_estimate_tools_tokens = estimate_tools_tokens


def truncate_text(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    max_chars = max(1, max_tokens * 3)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars for tier budget]"


_truncate_text = truncate_text


def truncate_message(msg: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    content = extract_message_content(msg.get("content"))
    return {**msg, "content": truncate_text(content, max_tokens)}


_truncate_message = truncate_message


def truncate_messages(messages: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
    remaining = max_tokens
    out: List[Dict[str, Any]] = []
    for msg in messages:
        need = message_tokens(msg)
        if need <= remaining:
            out.append(msg)
            remaining -= need
            continue
        if remaining > 64:
            out.append(truncate_message(msg, remaining))
        break
    return out


_truncate_messages = truncate_messages


def compress_history_stub(dropped: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for msg in dropped[-24:]:
        role = str(msg.get("role", "user"))
        content = extract_message_content(msg.get("content")).replace("\n", " ").strip()
        if not content:
            continue
        preview = content[:MESSAGE_PREVIEW_CHARS]
        suffix = "..." if len(content) > MESSAGE_PREVIEW_CHARS else ""
        lines.append(f"- {role}: {preview}{suffix}")
    body = "\n".join(lines) if lines else "(no recoverable text in dropped turns)"
    stub = (
        f"[TIER-AWARE CONTEXT TRIM - {len(dropped)} earlier turns compressed "
        f"to protect local MoE hardware]\n{body}"
    )
    try:
        from headroom_backends import compress_via_backend

        stub = compress_via_backend(stub, role="summary", mode="local")
    except Exception:
        pass
    if len(stub) > STUB_MAX_CHARS:
        stub = stub[:STUB_MAX_CHARS] + f"...[stub capped at {STUB_MAX_CHARS} chars]"
    return stub


_compress_history_stub = compress_history_stub


def messages_to_prompt(messages: List[Dict[str, Any]], max_chars: Optional[int] = None) -> str:
    """Flatten chat messages into a single prompt for bridge_dispatch."""
    parts: List[str] = []
    for msg in messages or []:
        role = str(msg.get("role", "user")).upper()
        content = extract_message_content(msg.get("content"))
        if not content.strip():
            continue
        parts.append(f"{role}:\n{content}")
    text = "\n\n".join(parts)
    if max_chars is not None and len(text) > max_chars:
        text = text[-max_chars:]
    return text


def fifo_pressure_reserve_tokens() -> int:
    """Tighten non-RP trim when FIFO depth is high (less prefill work per job)."""
    try:
        from inference_queue import get_inference_queue

        waiting = int(get_inference_queue().snapshot().get("waiting_count") or 0)
        if waiting >= 6:
            return 4096
        if waiting >= 3:
            return 2048
    except Exception:
        pass
    return 0


_fifo_pressure_reserve_tokens = fifo_pressure_reserve_tokens


def estimate_context_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(message_tokens(m) for m in messages)


def _flatten_and_maybe_log(messages: List[Dict[str, Any]], model: str) -> List[Dict[str, Any]]:
    """Late-bind flatten/log from the HTTP module (defined before this is called)."""
    import sovereign_openai_proxy as _proxy

    pre_flat = messages or []
    had_tool_shape = any(
        isinstance(m, dict)
        and (m.get("role") == "tool" or (m.get("role") == "assistant" and m.get("tool_calls")))
        for m in pre_flat
    )
    out = _proxy._flatten_tool_history_for_llama(messages)
    if had_tool_shape:
        _proxy._log_event(
            {
                "event": "proactive_tool_history_flatten",
                "phase": "trim_messages_tier_aware",
                "model": model,
                "orig_turns": len(pre_flat),
                "flat_turns": len(out or []),
            }
        )
    return out


def sliding_window_hydrate(
    messages: List[Dict[str, Any]],
    tail_messages: int = SLIDING_TAIL_MESSAGES,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Keep thread-anchor system prompt + last 6-8 turns.

    Stale entity/golden/tool-opt system blocks are dropped so
    entity_pre_inject can overlay current dossiers without contradiction.
    """
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    anchors: List[Dict[str, Any]] = []
    convo: List[Dict[str, Any]] = []
    dropped_stale = 0
    for msg in msgs:
        role = str(msg.get("role") or "")
        if role == "system":
            content = extract_message_content(msg.get("content"))
            if any(mark in content for mark in _STALE_SYSTEM_MARKERS):
                dropped_stale += 1
                continue
            if len(anchors) < 2:
                anchors.append(msg)
            continue
        convo.append(msg)
    tail_n = max(12, min(int(tail_messages), 16))  # 6-8 turns
    dropped_convo = max(0, len(convo) - tail_n)
    tail = convo[-tail_n:] if dropped_convo else convo
    out = list(anchors) + list(tail)
    meta = {
        "sliding_window": True,
        "anchor_n": len(anchors),
        "tail_n": len(tail),
        "dropped_stale_system": dropped_stale,
        "dropped_convo": dropped_convo,
        "original_n": len(msgs),
        "final_n": len(out),
    }
    return out, meta


def trim_messages_tier_aware(
    messages: List[Dict[str, Any]],
    model: str,
    extra_reserve_tokens: int = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trim chat history to the safe input budget for the resolved MoE tier.
    Preserves system prompts + recent turns; middle history becomes a stub.
    Roleplay tier bypasses trim -- full unfiltered working memory preserved.
    """
    from model_resource_manager import context_budget_for_tier, input_budget_for_tier
    import sovereign_openai_proxy as _proxy

    messages = _flatten_and_maybe_log(messages, model)
    slide_meta: Dict[str, Any] = {}
    try:
        non_sys = sum(1 for m in (messages or []) if str(m.get("role")) != "system")
        if non_sys > SLIDING_TAIL_MESSAGES:
            messages, slide_meta = sliding_window_hydrate(messages)
    except Exception:
        slide_meta = {}

    if _proxy._roleplay_route_requested(model, messages):
        original_tokens = sum(message_tokens(m) for m in messages)
        route = _proxy.preview_route_for_request(model, messages)
        input_cap = input_budget_for_tier("local_roleplay")
        if original_tokens <= input_cap:
            rp_meta = {
                "tier": "local_roleplay",
                "tier_budget_tokens": context_budget_for_tier("local_roleplay"),
                "input_cap_tokens": input_cap,
                "original_tokens_estimate": original_tokens,
                "original_message_count": len(messages),
                "trimmed": bool(slide_meta.get("dropped_convo")),
                "roleplay_bounded": False,
                "route_preview": route,
                "final_tokens_estimate": original_tokens,
                "final_message_count": len(messages),
            }
            if slide_meta:
                rp_meta["sliding_window"] = slide_meta
            return list(messages), rp_meta
        system_msgs = [m for m in messages if str(m.get("role")) == "system"]
        non_system = [m for m in messages if str(m.get("role")) != "system"]
        system_cap = max(1024, int(input_cap * 0.2))
        trimmed_system = truncate_messages(system_msgs, system_cap)
        system_used = sum(message_tokens(m) for m in trimmed_system)
        remaining = max(0, input_cap - system_used)
        kept_tail: List[Dict[str, Any]] = []
        first_kept_idx: Optional[int] = None
        for rev_i, msg in enumerate(reversed(non_system)):
            orig_idx = len(non_system) - 1 - rev_i
            need = message_tokens(msg)
            if need <= remaining:
                if first_kept_idx is None:
                    first_kept_idx = orig_idx
                kept_tail.insert(0, msg)
                remaining -= need
                continue
            if not kept_tail and remaining > 64:
                first_kept_idx = orig_idx
                kept_tail.insert(0, truncate_message(msg, remaining))
                remaining = 0
            break
        dropped_middle = non_system[:first_kept_idx] if first_kept_idx is not None else list(non_system)
        result = list(trimmed_system)
        if dropped_middle:
            result.append({"role": "user", "content": compress_history_stub(dropped_middle)})
        result.extend(kept_tail)
        final_tokens = sum(message_tokens(m) for m in result)
        rp_out = {
            "tier": "local_roleplay",
            "tier_budget_tokens": context_budget_for_tier("local_roleplay"),
            "input_cap_tokens": input_cap,
            "original_tokens_estimate": original_tokens,
            "original_message_count": len(messages),
            "trimmed": True,
            "roleplay_bounded": True,
            "dropped_turns": len(dropped_middle),
            "kept_tail_turns": len(kept_tail),
            "route_preview": route,
            "final_tokens_estimate": final_tokens,
            "final_message_count": len(result),
            "compression": "roleplay_tail_preserve",
        }
        if slide_meta:
            rp_out["sliding_window"] = slide_meta
        return result, rp_out

    route = _proxy.preview_route_for_request(model, messages)
    tier = str(route.get("tier") or "local_hot")
    tier_budget = context_budget_for_tier(tier)
    input_cap = input_budget_for_tier(tier, extra_reserve_tokens=extra_reserve_tokens)

    original_tokens = sum(message_tokens(m) for m in messages)
    meta: Dict[str, Any] = {
        "tier": tier,
        "tier_budget_tokens": tier_budget,
        "input_cap_tokens": input_cap,
        "original_tokens_estimate": original_tokens,
        "original_message_count": len(messages),
        "trimmed": False,
        "route_preview": route,
    }

    if original_tokens <= input_cap:
        meta["final_tokens_estimate"] = original_tokens
        meta["final_message_count"] = len(messages)
        if slide_meta:
            meta["sliding_window"] = slide_meta
            meta["trimmed"] = bool(slide_meta.get("dropped_convo"))
        return list(messages), meta

    system_msgs = [m for m in messages if str(m.get("role")) == "system"]
    non_system = [m for m in messages if str(m.get("role")) != "system"]

    system_cap = max(512, int(input_cap * SYSTEM_BUDGET_RATIO))
    trimmed_system = truncate_messages(system_msgs, system_cap)
    system_used = sum(message_tokens(m) for m in trimmed_system)
    remaining = max(0, input_cap - system_used)

    kept_tail = []
    first_kept_idx = None
    for rev_i, msg in enumerate(reversed(non_system)):
        orig_idx = len(non_system) - 1 - rev_i
        need = message_tokens(msg)
        if need <= remaining:
            if first_kept_idx is None:
                first_kept_idx = orig_idx
            kept_tail.insert(0, msg)
            remaining -= need
            continue
        if not kept_tail and remaining > 64:
            first_kept_idx = orig_idx
            kept_tail.insert(0, truncate_message(msg, remaining))
            remaining = 0
        break

    if first_kept_idx is not None:
        dropped_middle = non_system[:first_kept_idx]
    else:
        dropped_middle = list(non_system)

    result = list(trimmed_system)
    if dropped_middle:
        result.append({"role": "user", "content": compress_history_stub(dropped_middle)})
    result.extend(kept_tail)

    final_tokens = sum(message_tokens(m) for m in result)
    if slide_meta:
        meta["sliding_window"] = slide_meta
    if final_tokens > input_cap:
        prompt_text = messages_to_prompt(result, max_chars=input_cap * 3)
        result = [{"role": "user", "content": prompt_text}]
        final_tokens = estimate_tokens(prompt_text)
        meta["hard_cap_applied"] = True

    meta.update(
        {
            "trimmed": True,
            "dropped_turns": len(dropped_middle),
            "kept_tail_turns": len(kept_tail),
            "final_tokens_estimate": final_tokens,
            "final_message_count": len(result),
            "compression": "middle_history_stub",
        }
    )
    return result, meta
