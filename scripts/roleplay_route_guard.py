#!/usr/bin/env python3
"""Shared roleplay route detection and strict-tier isolation helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from roleplay_subsystem import ROLEPLAY_BLOCK_MESSAGE


def extract_phronesis_body(body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    body = body or {}
    ph = body.get("phronesis")
    if isinstance(ph, dict):
        return ph
    extra = body.get("extra_body")
    if isinstance(extra, dict):
        ph = extra.get("phronesis")
        if isinstance(ph, dict):
            return ph
    return {}


def _flatten_message_content(content: Any) -> str:
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content or "")


def collect_message_blobs(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Gather all text surfaces used for roleplay detection."""
    user_texts: List[str] = []
    system_blob = ""
    all_blob_parts: List[str] = []
    for msg in messages or []:
        role = str(msg.get("role") or "").lower()
        text = _flatten_message_content(msg.get("content"))
        if not text.strip():
            continue
        all_blob_parts.append(text)
        if role in ("user", "developer"):
            user_texts.append(text)
        if role == "system":
            system_blob = f"{system_blob}\n{text}"
    return {
        "user_texts": user_texts,
        "last_user": user_texts[-1] if user_texts else "",
        "system_blob": system_blob.strip(),
        "all_blob": "\n".join(all_blob_parts),
    }


def is_uncensored_roleplay_route(
    *,
    prompt: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    task_type: Optional[str] = None,
    platform: str = "",
    model: str = "",
    routing: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> bool:
    routing = routing or {}
    ph = extract_phronesis_body(body)
    plat = str(routing.get("platform") or ph.get("platform") or platform or "").lower()

    try:
        from discord_roleplay_connector import (
            has_explicit_roleplay_user_trigger,
            is_alice_roleplay_discord_location,
        )

        in_alice = is_alice_roleplay_discord_location(
            chat_id=str(routing.get("chat_id") or ph.get("chat_id") or ""),
            thread_id=str(routing.get("thread_id") or ph.get("thread_id") or ""),
            parent_channel_id=str(
                routing.get("parent_channel_id") or ph.get("parent_channel_id") or ""
            ),
        )
    except Exception:
        in_alice = plat == "alice-roleplay"
        has_explicit_roleplay_user_trigger = None  # type: ignore

    if routing.get("force_roleplay") and in_alice:
        return True
    if ph.get("force_roleplay") and in_alice:
        return True
    if in_alice:
        return True

    blobs = collect_message_blobs(messages or [])
    last_user = str(blobs.get("last_user") or "")
    if callable(has_explicit_roleplay_user_trigger):
        if has_explicit_roleplay_user_trigger(last_user):
            return True
        if prompt and has_explicit_roleplay_user_trigger(prompt):
            return True

    return False


def roleplay_block_result(*, provenance: Optional[Dict[str, Any]] = None, attempts: Optional[List[Any]] = None) -> Dict[str, Any]:
    prov = dict(provenance or {})
    prov["uncensored_route"] = True
    prov["roleplay_block"] = True
    prov["selected_backend"] = "blocked"
    return {
        "response": ROLEPLAY_BLOCK_MESSAGE,
        "model": "rocinante-12b",
        "tier": "local_roleplay",
        "success": False,
        "provenance": prov,
        "attempts": attempts or [],
        "roleplay_blocked": True,
    }
