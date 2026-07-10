#!/usr/bin/env python3
"""
proactive_routing_policy.py - Classify requests for local-only vs T2 fleet offload.

Local-first invariant (when in doubt, keep local):
  - Roleplay, tools, vault/private paths, PII, explicit content -> local_only (Qwythos @ :8090)
  - Public, non-sensitive research/synthesis with clear intent -> offload_compute (T2/T3)
  - Realtime context that should stay with local voice -> augment_local (existing prefetch)
  - Ambiguous or borderline prompts -> local_first (never guess offload)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from escalation_router import is_roleplay_route

ROUTING_LOCAL_ONLY = "local_only"
ROUTING_AUGMENT_LOCAL = "augment_local"
ROUTING_OFFLOAD_COMPUTE = "offload_compute"
ROUTING_LOCAL_FIRST = "local_first"

_SENSITIVE_MARKERS = (
    "password",
    "api_key",
    "api key",
    "secret",
    "private_key",
    "ssn",
    "social security",
    "credit card",
    "medical record",
    ".env",
    "bitwarden",
    "discord_bot_token",
    "grok_api_key",
    "openrouter_api_key",
)

_EXPLICIT_MARKERS = (
    "ooc:",
    "bedroom",
    "uncensored",
    "harem",
    "explicit",
    "nsfw",
    "erotic",
)

_PRIVATE_PATH_RE = re.compile(
    r"(?i)(?:[d-z]:\\|~/|\./)?(?:phronesisvault|hermesdata|roleplay-sandbox|\.env|secrets?\\)",
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

_PUBLIC_OFFLOAD_INTENTS = (
    "summarize",
    "summary of",
    "explain",
    "what is",
    "what are",
    "how does",
    "compare",
    "research",
    "latest news",
    "breaking news",
    "current events",
    "look up",
    "search for",
    "web search",
    "public api",
    "open source",
    "trends in",
    "overview of",
)

_TOOL_INTENT_MARKERS = (
    "read_file",
    "write_file",
    "terminal",
    "run_terminal",
    "tool_call",
    "execute:",
    "powershell",
    "d:\\hermesdata",
    "d:\\phronesisvault",
)


def _message_blob(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
        if role == "tool":
            parts.append(str(msg.get("name") or ""))
    return "\n".join(parts)


def contains_sensitive_content(text: str) -> Tuple[bool, str]:
    low = (text or "").lower()
    for marker in _SENSITIVE_MARKERS:
        if marker in low:
            return True, f"sensitive:{marker}"
    for marker in _EXPLICIT_MARKERS:
        if marker in low:
            return True, f"explicit:{marker}"
    if _PRIVATE_PATH_RE.search(text or ""):
        return True, "private_path"
    if _EMAIL_RE.search(text or ""):
        return True, "email_pii"
    if _PHONE_RE.search(text or ""):
        return True, "phone_pii"
    return False, ""


def is_fleet_safe_for_offload(text: str) -> Tuple[bool, str]:
    """Post-sanitize gate: block fleet dispatch if any private/explicit signal remains."""
    sensitive, reason = contains_sensitive_content(text)
    if sensitive:
        return False, reason
    if _PRIVATE_PATH_RE.search(text or ""):
        return False, "private_path_residual"
    return True, ""


def _ambiguous_prompt(prompt: str, intent_reasons: List[str]) -> bool:
    """Short/generic prompts without clear public intent stay local."""
    text = (prompt or "").strip()
    if not text:
        return True
    if intent_reasons:
        return False
    if len(text) < 120:
        return True
    return False


def sanitize_for_fleet(prompt: str) -> str:
    """Strip obvious local identifiers before sending to free cloud models."""
    out = prompt or ""
    out = _PRIVATE_PATH_RE.sub("[LOCAL_PATH_REDACTED]", out)
    out = _EMAIL_RE.sub("[EMAIL_REDACTED]", out)
    out = _PHONE_RE.sub("[PHONE_REDACTED]", out)
    out = re.sub(r"(?i)\b(?:api[_-]?key|password|token)\s*[:=]\s*\S+", "[CREDENTIAL_REDACTED]", out)
    return out.strip()


def _has_tool_context(messages: List[Dict[str, Any]], body: Dict[str, Any]) -> bool:
    if body.get("tools") or body.get("tool_choice"):
        return True
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool":
            return True
        if msg.get("tool_calls"):
            return True
    blob = _message_blob(messages).lower()
    return any(m in blob for m in _TOOL_INTENT_MARKERS)


def _public_offload_intent(prompt: str, routing: Dict[str, Any]) -> Tuple[bool, List[str]]:
    low = (prompt or "").lower()
    matched: List[str] = []
    for phrase in _PUBLIC_OFFLOAD_INTENTS:
        if phrase in low:
            matched.append(f"intent:{phrase}")
    task = str(routing.get("task_type") or "").lower()
    if task in ("research", "web", "summarize"):
        matched.append(f"task_type:{task}")
    if re.search(r"\b(today|this week|202[4-9])\b", low) and any(
        k in low for k in ("news", "ai", "tech", "release", "announce")
    ):
        matched.append("realtime_public_news")
    return bool(matched), matched


def classify_proactive_routing(
    prompt: str,
    routing: Dict[str, Any],
    messages: List[Dict[str, Any]],
    body: Optional[Dict[str, Any]] = None,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Decide how :8091 should route before T0 GPU dispatch.

    Returns dict with mode, reasons, sanitized_prompt (for fleet), eligible.
    """
    body = body or {}
    headers = headers or {}
    reasons: List[str] = []

    if is_roleplay_route(routing):
        return {
            "mode": ROUTING_LOCAL_ONLY,
            "eligible": False,
            "reasons": ["roleplay_sandbox"],
            "sanitized_prompt": prompt,
        }

    if _has_tool_context(messages, body):
        return {
            "mode": ROUTING_LOCAL_ONLY,
            "eligible": False,
            "reasons": ["tools_or_local_ops_required"],
            "sanitized_prompt": prompt,
        }

    blob = _message_blob(messages)
    for surface in (blob, prompt or ""):
        sensitive, sens_reason = contains_sensitive_content(surface)
        if sensitive:
            return {
                "mode": ROUTING_LOCAL_ONLY,
                "eligible": False,
                "reasons": [sens_reason],
                "sanitized_prompt": prompt,
            }

    hdr_route = (headers.get("X-Phronesis-Routing") or headers.get("x-phronesis-routing") or "").strip().lower()
    if hdr_route in ("local", "local-only", "sovereign"):
        return {
            "mode": ROUTING_LOCAL_ONLY,
            "eligible": False,
            "reasons": ["header_force_local"],
            "sanitized_prompt": prompt,
        }

    intent_ok, intent_reasons = _public_offload_intent(prompt, routing)

    if hdr_route in ("offload", "fleet", "t2"):
        reasons.append("header_force_offload")
        sanitized = sanitize_for_fleet(prompt)
        safe, block_reason = is_fleet_safe_for_offload(sanitized)
        if not safe:
            return {
                "mode": ROUTING_LOCAL_ONLY,
                "eligible": False,
                "reasons": [block_reason, "header_offload_blocked_unsafe"],
                "sanitized_prompt": prompt,
            }
        return {
            "mode": ROUTING_OFFLOAD_COMPUTE,
            "eligible": True,
            "reasons": reasons,
            "sanitized_prompt": sanitized,
        }

    if intent_ok:
        if _ambiguous_prompt(prompt, intent_reasons):
            return {
                "mode": ROUTING_LOCAL_FIRST,
                "eligible": False,
                "reasons": ["ambiguous_keep_local"],
                "sanitized_prompt": prompt,
            }
        sanitized = sanitize_for_fleet(prompt)
        safe, block_reason = is_fleet_safe_for_offload(sanitized)
        if not safe:
            return {
                "mode": ROUTING_LOCAL_ONLY,
                "eligible": False,
                "reasons": [block_reason, "offload_blocked_unsafe"],
                "sanitized_prompt": prompt,
            }
        return {
            "mode": ROUTING_OFFLOAD_COMPUTE,
            "eligible": True,
            "reasons": intent_reasons,
            "sanitized_prompt": sanitized,
        }

    # Borderline realtime - augment path handles; keep Qwythos as voice.
    from router_bridge import detect_opportunistic_fleet_triggers

    triggers = detect_opportunistic_fleet_triggers(
        prompt=prompt,
        task_type=routing.get("task_type"),
        context_tokens_estimate=len(prompt) // 4 + 4000,
    )
    if triggers.get("should_route") and "latest_external_knowledge" in (triggers.get("matched_triggers") or []):
        return {
            "mode": ROUTING_AUGMENT_LOCAL,
            "eligible": False,
            "reasons": ["realtime_augment_local"],
            "sanitized_prompt": sanitize_for_fleet(prompt),
            "triggers": triggers.get("matched_triggers"),
        }

    return {
        "mode": ROUTING_LOCAL_FIRST,
        "eligible": False,
        "reasons": ["default_local_first"],
        "sanitized_prompt": prompt,
    }