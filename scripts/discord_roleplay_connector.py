#!/usr/bin/env python3
"""
Session-id roleplay routing scan (Discord snowflakes are one mouth's IDs).

Not a Discord SDK/HTTP client. Gateway adapters (Discord today; others later)
stamp chat_id/thread_id/parent_channel_id into the OpenAI body. This module
maps those IDs + slash/colon markers onto local_roleplay.

Rewrites slash triggers that Hermes gateway would swallow as unknown commands,
detects alice-roleplay thread IDs, and logs ingest traces for E2E debugging.
New mouths: do not import discord.py here; pass IDs from the adapter.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TRACE_LOG = Path(r"D:\PhronesisVault\Operations\logs\discord-proxy-ingest-trace.jsonl")

ROLEPLAY_SLASH_PREFIXES = (
    "/roleplay",
    "/rp",
    "/narrative",
)

ROLEPLAY_COLON_PREFIXES = (
    "ROLEPLAY_MODE:",
    "UNCENSORED_ROLEPLAY:",
    "ROLEPLAY:",
)

ROLEPLAY_MODEL = "phronesis-sovereign-roleplay"
ALICE_ROLEPLAY_CHANNEL_ID = "1519509288286949466"
# IC heat only. T3 Grok and house-facts stay off here.
ALICE_ROLEPLAY_HEAT_IDS = frozenset({
    "1519512763863666810",
    "1519522216851673190",
    "1519529411056242779",
    "1521146755985576116",
    "1523604530338730004",
    "1524821864956956793",  # Harem Image
    "1525174401740312707",  # New group / story+inline
    "1525214795236773918",  # Just Alice pure IC
    "1532906132056838184",  # Millbrook Kingdom
    "1524552417096761384",  # Voyeur training
    "1524594840136843445",  # Character cards
})
# Under the sandbox parent but factual ops. Not IC. T3 may hop.
ALICE_ROLEPLAY_OPS_IDS = frozenset({
    "1522325123817013269",  # Sandbox infra
    "1528335166462759102",  # Arch/firewall
    "1522330326733422713",  # Interviews + character (grunt)
})
# Location wall (heat + ops). Do not use this for T3-block / IC layer.
ALICE_ROLEPLAY_THREAD_IDS = ALICE_ROLEPLAY_HEAT_IDS | ALICE_ROLEPLAY_OPS_IDS


def _id_set(*values: str) -> set[str]:
    return {str(x).strip() for x in values if str(x).strip()}


def is_alice_roleplay_discord_location(
    *,
    chat_id: str = "",
    parent_channel_id: str = "",
    thread_id: str = "",
) -> bool:
    """True for #alice-roleplay and every child (heat + ops). Sandbox wall."""
    ids = _id_set(chat_id, parent_channel_id, thread_id)
    if ALICE_ROLEPLAY_CHANNEL_ID in ids:
        return True
    if parent_channel_id == ALICE_ROLEPLAY_CHANNEL_ID:
        return True
    return bool(ids & ALICE_ROLEPLAY_THREAD_IDS)


def is_alice_roleplay_heat(
    *,
    chat_id: str = "",
    parent_channel_id: str = "",
    thread_id: str = "",
) -> bool:
    """IC heat only. Ops children (arch/infra/interviews) are False so T3 can hop."""
    ids = _id_set(chat_id, thread_id)
    if ids & ALICE_ROLEPLAY_OPS_IDS:
        return False
    if ids & ALICE_ROLEPLAY_HEAT_IDS:
        return True
    if ALICE_ROLEPLAY_CHANNEL_ID in ids:
        return True
    return False


def has_explicit_roleplay_user_trigger(text: str) -> bool:
    """User-initiated roleplay only ? slash rewrite or colon trigger."""
    raw = (text or "").strip()
    if not raw:
        return False
    if is_roleplay_slash_command(raw):
        return True
    return has_colon_roleplay_trigger(raw)

_PLATFORM_TAG_RE = re.compile(
    r"\[\s*platform\s*:\s*([^\]]+)\]",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_roleplay_slash_command(text: str) -> bool:
    t = (text or "").strip().lower()
    for prefix in ROLEPLAY_SLASH_PREFIXES:
        if t == prefix.lstrip("/") or t == prefix or t.startswith(prefix + " "):
            return True
    return False


def rewrite_roleplay_slash(text: str) -> str:
    """Convert /roleplay or /rp to colon trigger Hermes gateway accepts as TEXT."""
    raw = (text or "").strip()
    lower = raw.lower()
    for prefix in ROLEPLAY_SLASH_PREFIXES:
        p_lower = prefix.lower()
        if lower == p_lower or lower == p_lower.lstrip("/"):
            return "ROLEPLAY_MODE:"
        if lower.startswith(p_lower + " "):
            rest = raw[len(prefix) :].strip()
            return f"ROLEPLAY_MODE: {rest}".strip()
    return raw


def has_colon_roleplay_trigger(text: str) -> bool:
    upper = (text or "").strip().upper()
    return any(upper.startswith(p) for p in ROLEPLAY_COLON_PREFIXES)


def extract_platform_tag(text: str) -> Optional[str]:
    m = _PLATFORM_TAG_RE.search(text or "")
    if not m:
        return None
    return m.group(1).strip().lower()


def resolve_discord_platform_marker(
    *,
    chat_name: str = "",
    channel_id: str = "",
    parent_channel_id: str = "",
    thread_id: str = "",
) -> str:
    """Return platform string for router_bridge / proxy."""
    ids = {str(x) for x in (channel_id, parent_channel_id, thread_id) if x}
    name_l = (chat_name or "").lower()
    if is_alice_roleplay_discord_location(
        chat_id=channel_id,
        parent_channel_id=parent_channel_id,
        thread_id=thread_id,
    ):
        return "alice-roleplay"
    if "alice-roleplay" in name_l or "#alice-roleplay" in name_l:
        return "alice-roleplay"
    return "discord"


def normalize_discord_inbound_text(
    text: str,
    *,
    chat_name: str = "",
    channel_id: str = "",
    parent_channel_id: str = "",
    thread_id: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    Normalize Discord user text before MessageEvent creation.
    Rewrites roleplay slashes so gateway does not treat them as unknown commands.
    """
    raw = (text or "").strip()
    meta: Dict[str, Any] = {
        "raw_len": len(raw),
        "rewrote_slash": False,
        "colon_trigger": False,
        "platform_marker": None,
        "force_roleplay_model": False,
    }
    if not raw:
        return raw, meta

    platform_tag = extract_platform_tag(raw)
    if platform_tag:
        meta["platform_marker"] = platform_tag

    normalized = raw
    if is_roleplay_slash_command(raw):
        normalized = rewrite_roleplay_slash(raw)
        meta["rewrote_slash"] = True

    if has_colon_roleplay_trigger(normalized):
        meta["colon_trigger"] = True

    plat = platform_tag or resolve_discord_platform_marker(
        chat_name=chat_name,
        channel_id=channel_id,
        parent_channel_id=parent_channel_id,
        thread_id=thread_id,
    )
    meta["resolved_platform"] = plat
    in_alice = is_alice_roleplay_discord_location(
        chat_id=channel_id,
        parent_channel_id=parent_channel_id,
        thread_id=thread_id,
    )
    if in_alice:
        meta["force_roleplay_model"] = True
        meta["sandbox"] = "alice-roleplay"

    return normalized, meta


def log_discord_ingest_trace(
    *,
    stage: str,
    raw_text: str,
    normalized_text: str,
    meta: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        entry = {
            "timestamp": _utc_now(),
            "stage": stage,
            "raw_text": raw_text,
            "normalized_text": normalized_text,
            "raw_repr": repr(raw_text),
            "normalized_repr": repr(normalized_text),
            "meta": meta or {},
            "extra": extra or {},
        }
        try:
            from jsonl_log_rotator import append_jsonl as _rot_append

            _rot_append(TRACE_LOG, entry, mode="rename", stamp=False)
            return
        except Exception:
            pass
        TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def scan_messages_for_roleplay(
    messages: List[Dict[str, Any]],
    *,
    default_model: str = "phronesis-sovereign-auto",
    body: Optional[Dict[str, Any]] = None,
    chat_id: str = "",
    parent_channel_id: str = "",
    thread_id: str = "",
) -> Dict[str, Any]:
    """
    Inspect OpenAI-style messages from Hermes before proxy dispatch.
    Returns model/platform overrides and diagnostic trace.
    """
    try:
        from roleplay_route_guard import collect_message_blobs, extract_phronesis_body

        blobs = collect_message_blobs(messages)
        last_user = str(blobs.get("last_user") or "")
        system_blob = str(blobs.get("system_blob") or "")
        all_blob = str(blobs.get("all_blob") or "")
        user_texts: List[str] = list(blobs.get("user_texts") or [])
    except Exception:
        last_user = ""
        system_blob = ""
        all_blob = ""
        user_texts = []

    ph = {}
    try:
        from roleplay_route_guard import extract_phronesis_body

        ph = extract_phronesis_body(body)
    except Exception:
        pass

    in_alice = is_alice_roleplay_discord_location(
        chat_id=chat_id,
        parent_channel_id=parent_channel_id,
        thread_id=thread_id,
    )
    platform_tag = extract_platform_tag(last_user)
    chat_name = ""
    m = re.search(r"channel:\s*([^\n]+)", system_blob, re.IGNORECASE)
    if m:
        chat_name = m.group(1).strip()

    if not in_alice and chat_name and "alice-roleplay" in chat_name.lower():
        in_alice = True
    # Do not scan raw system_blob for #alice-roleplay ? Hermes default stance
    # mentions it as policy text and would false-positive api_server/cron turns.

    if not chat_id:
        for pattern in (
            r"channel_id[:\s]+(\d{15,25})",
            r"chat_id[:\s]+(\d{15,25})",
            r"thread[:\s]+(\d{15,25})",
        ):
            m_id = re.search(pattern, system_blob, re.IGNORECASE)
            if m_id and is_alice_roleplay_discord_location(chat_id=m_id.group(1)):
                chat_id = m_id.group(1)
                in_alice = True
                break

    if in_alice:
        platform = "alice-roleplay"
    else:
        platform = str(ph.get("platform") or "discord")

    model = default_model
    force_roleplay = False
    reasons: List[str] = []

    if "roleplay" in (default_model or "").lower():
        force_roleplay = True
        model = default_model
        reasons.append("channel_model=roleplay")

    if in_alice:
        force_roleplay = True
        reasons.append("sandbox=alice-roleplay")
        if platform_tag == "alice-roleplay":
            reasons.append("platform_tag=alice-roleplay")
        if ph.get("force_roleplay"):
            reasons.append("phronesis_body")
        for idx, text in enumerate(reversed(user_texts)):
            if has_explicit_roleplay_user_trigger(text):
                reasons.append(f"explicit_user_trigger:turn-{idx}")
                break
        model = str(ph.get("model") or ROLEPLAY_MODEL)
    elif platform_tag == "alice-roleplay":
        # Tag pasted outside sandbox ? do not route to roleplay tier.
        platform = "discord"
        reasons.append("platform_tag_ignored_outside_sandbox")

    probe_text = last_user
    return {
        "model": model,
        "platform": platform,
        "last_user_text": last_user,
        "chat_name_hint": chat_name,
        "force_roleplay": force_roleplay,
        "reasons": reasons,
        "probe_chars": len(probe_text),
        "user_turn_count": len(user_texts),
    }
