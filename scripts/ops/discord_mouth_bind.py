#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord mouth honesty -- conversation first, invent-less.

Product law 2026-08-14 / 2026-08-14b: every Discord thread talks
naturally first. Tools only when a real job needs them. Only Roleplay
Sandbox is special-cased for ERP (owned by rp_ic_layer, stacked on
top of talk-first -- not this file).

This file no longer replaces ordinary ops-room replies with
"tools-first failed". That hard gate blocked conversation after /reset
(empty session => no allowlisted tool => every line replaced).

What remains:
  1. Banner mute: drop empty-model / provider-unreachable / fallback
     status theater on every Discord room (not only the old banner list).
  2. Light honesty: strip sentences that name a .py/.ps1 door that is not
     allowlisted and does not exist on disk. Ordinary talk passes.
  3. configure_ops_mouth_agent is a no-op (no local-or-silence bind).

Does not route. Does not start models. Does not send Kindroid. Does not
scan K:. Does not touch stills / force-still / RP ERP.

  python D:/HermesData/discord_mouth_bind.py --status
"""
from __future__ import annotations

import argparse
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

HERMES = Path(r"D:\HermesData")
STATE = HERMES / "state" / "discord_mouth_bind_latest.json"
SCRIPTS = HERMES / "scripts"
OPS = SCRIPTS / "ops"
SEAL = "discord-mouth-bind-v3-2026-08-26"
FAIL_CLOSED = "tools-first failed"  # kept for receipt/tests; apply_gate no longer posts it
HONEST_NO_DOOR = "No door named %s. I can talk, or we can run a real script."
COLLAPSE_LINE = (
    "Empty model that turn. Say it once more -- I stay in partner voice."
)
# Adapter collapse emits these on purpose. They are partner talk, not banners.
# 2026-08-14 Soul Forge: 14065->117 then filter_outbound_status dropped the
# "glitched into tool-schema" line because it was also in _STATUS_THEATER_RE.
ADAPTER_SCHEMA_RECOVERY = (
    "I glitched into tool-schema instead of a real answer "
    "(suppressed). One more plain ask and I'll stay in partner voice."
)
ADAPTER_TOOL_DUMP_RECOVERY = (
    "I started dumping tool internals instead of answering you "
    "(suppressed). Ask once more in plain words -- I'll reply as partner, "
    "not schema."
)
# Live adapter (pre-reload) still emits U+2014. Source stays 7-bit ASCII.
ADAPTER_TOOL_DUMP_RECOVERY_LIVE = (
    "I started dumping tool internals instead of answering you "
    "(suppressed). Ask once more in plain words \u2014 I'll reply as partner, "
    "not schema."
)
try:
    from tool_call_fixer import IC_LEAK_RECOVERY as IC_BEAT_AGAIN
    from tool_call_fixer import LEAK_RECOVERY as TOOL_SYNTAX_LEAK_LINE
except Exception:  # pragma: no cover
    TOOL_SYNTAX_LEAK_LINE = (
        "I glitched into tool-syntax instead of a real answer (suppressed). "
        "Ask the same thing again in plain talk. Skip /reset -- that wipes the question."
    )
    IC_BEAT_AGAIN = "I'm still here. Say that beat again. No tools."
_RECOVERY_PASS = frozenset(
    {
        COLLAPSE_LINE.strip().lower(),
        ADAPTER_SCHEMA_RECOVERY.strip().lower(),
        ADAPTER_TOOL_DUMP_RECOVERY.strip().lower(),
        ADAPTER_TOOL_DUMP_RECOVERY_LIVE.strip().lower(),
    }
)
TALK_FIRST_LOCK = (
    "TALK FIRST. You are Alice (I/me) to Jeff (you). Converse like a person. "
    "Use tools only when the job needs them (search, file, journal, land, still). "
    "Never dump tool schemas, [Called ...] or tool JSON. "
    "Live news: search or say you did not look it up. "
    "PLANNING ASK (where we sit / broad strokes / holistic / plan): work/partner voice. "
    "Quote a real door or say you did not look. Never invent Wave names, DBs, "
    "RFID fleets, adventure titles, or fake kitchen ctx. "
    "Live kitchen is Qwythos 9B @ 128k on :8090."
)

# Real doors we will not strip from outbound talk.
ALLOWLIST_NEEDLES = (
    "silo.py",
    "silo_discord_six_numbers.py",
    "silo_ctl.py",
    "silo_rock_solid_board.py",
    "hermes_image.py",
    "kindroid_bridge.py",
    "send_to_sister.py",
    "speak_and_trust_once.py",
    "foundation_integrity_once.py",
    "rp_sandbox_firewall_selfcheck.py",
    "image_delivery_policy.py",
    "image_session.py",
    "free_sfw_bench.py",
    "autonomy_growth_once.py",
    "skill_librarian.py",
    "learn_land_once.py",
    "ssot_skill_homes_check.py",
    "housekeeping_once.py",
    "idea_retention.py",
    "alice_open_loops.py",
    "discord_mouth_bind.py",
)

OPS_ROOMS = frozenset(
    {
        "1524529242019336434",  # Data silo
        "1522325123817013269",  # RP-sandbox infra
        "1526952913413607454",  # model-mgmt
        "1524846849360531456",  # Grok coord
        "1528335166462759102",  # RP-arch
        "1522330326733422713",  # Interviews
        "1526594007092826316",  # Jan Bloom
        "1523156115808845926",  # Factual
        "1523740118370881546",  # Travel
    }
)
# RP *action beat* only. Do NOT match markdown **bold** (Grok hire 2026-08-26:
# 481-char work reply starting with ** was replaced by the 59-char Work-mode slap).
_OPS_IC_OPEN_RE = re.compile(r"(?s)^\s*\*(?!\*)[A-Za-z][^*]{1,160}\*")
_STALE_SAT_BLOB_RE = re.compile(
    r"(?is)Core is green.{0,160}SAT.{0,80}2026-08-21T21:02:41"
)
# Live Jan 2026-08-26 posted the leak with no closing ]. $ must count.
_REPLY_TO_MSG_RE = re.compile(
    r"(?is)\[Reply to message\s+`[^`]+`[^\]]*(?:\]|$)"
)
_ASSISTANT_THEATER_RE = re.compile(
    r"(?im)^\s*(?:ASSISTANT|USER|SYSTEM)\s*:\s*"
)
_Q_THEATER_RE = re.compile(r"(?im)^\s*Q:\s*")
_FAKE_SIX_RE = re.compile(
    r"(?is)(?:six_numbers[^\n]{0,80}|```)\s*123456\b"
    r"|here is the six_numbers line:[^\n]{0,40}123456"
)
_RUN_JSON_WRAP_RE = re.compile(
    r'(?is)RUN:\s*.{0,280}\{\s*"output"\s*:'
)
_SILO_REAL_RE = re.compile(r"(?is)SILO_SIX_NUMBERS|\bregistry_total\s*=")
_SAT_CORE_RE = re.compile(r"(?is)Core is green.{0,80}SAT\s+20")
SILO_ROOM = "1524529242019336434"
RP_ARCH_ROOM = "1528335166462759102"
JAN_ROOM = "1526594007092826316"
SILO_HONEST = (
    "I did not run silo_discord_six_numbers.py. "
    "No invented 123456 and no RUN JSON wrap. "
    "Paste SILO_SIX_NUMBERS from that door, or say I did not look."
)
FIREWALL_HONEST = (
    "Wrong door. This room quotes rp_sandbox_firewall_selfcheck.py pass/fail. "
    "SAT belongs in model-mgmt. I did not run the firewall door."
)
JAN_HONEST = (
    "I did not open a BooksBloom/Jan file. "
    "No [Reply to message] theater. Quote a real D:\\ path or say I did not look."
)

# JA, Beauty, RP parent + known heat children. Status theater dies here.
BANNER_ROOMS = frozenset(
    {
        "1525214795236773918",  # Just Alice
        "1521146755985576116",  # Beauty / seed
        "1519509288286949466",  # alice-roleplay parent
        "1532906132056838184",  # Millbrook
        "1525174401740312707",  # Group RP
        "1523604530338730004",  # Alice RP child
        "1524821864956956793",  # Harem image
        "1519512763863666810",
        "1519522216851673190",
        "1519529411056242779",
    }
)

# Compression / token-count pipeline leaks — drop silently on every room.
_COMPRESSION_LEAK_RE = re.compile(
    r"(context compression deferred|"
    r"compression aborted|"
    r"context is over the compression threshold|"
    r"finish_reason\s*=\s*length|"
    r"compression is currently blocked|"
    r"summary still streaming|"
    r"no messages were dropped|"
    r"~\d[\d,]*\s+tokens\s*>=|"
    r"generation hit the output token cap)",
    re.I,
)

# Empty / fallback / retry banners the 9B and gateway both emit.
_STATUS_THEATER_RE = re.compile(
    r"(empty response from model|model returned no content|"
    r"provider unreachable|"
    r"switching to fallback provider|model returning empty responses|"
    r"empty response after tool calls|nudging to continue|"
    r"model returned empty after tool|switched to fallback model|"
    r"primary model failed .{0,80}switching to fallback|"
    r"empty/?malformed response|"
    r"retrying\s*\(\d+\s*/\s*\d+|"
    r"billing or credits exhausted|"
    r"rate limited .{0,40}switching to fallback|"
    r"the model provider failed after retries|"
    r"model provider failed after retries|"
    r"redirected current run|"
    r"processing completed but no response was generated|"
    r"interrupting current task|"
    r"iteration budget exhausted)",
    re.I,
)

# Poke / XO / hop-law injects that leaked into JA, Millbrook, and IC children.
_IC_INJECT_RE = re.compile(
    r"(?is)^\s*(?:\*\*)?(?:\[GROK OPS\]|HOP-LAW|ALICE-LIVE|\[Hermes XO)",
)

# Model sometimes pastes the delivery tag as visible chat.
_MEDIA_LINE_RE = re.compile(r"(?im)^\s*`{0,3}MEDIA:\s*\S+.*$", re.M)
_MEDIA_INLINE_RE = re.compile(
    r"(?i)`{0,3}MEDIA:\s*(?:[A-Za-z]:\\|/|~/)[^\s`]+`{0,3}"
)
# Invented placeholder (Beauty 2026-08-22: "MEDIA: [path]" with no file)
_MEDIA_PLACEHOLDER_RE = re.compile(
    r"(?i)`{0,3}MEDIA:\s*\[(?:path|file|still|image|media)\]`{0,3}"
)

# Model sometimes pastes a raw tool call as chat (silo 2026-08-16).
_TOOL_CALL_LEAK_RE = re.compile(
    r"(?is)(?:^|\n)\s*(?:terminal|execute_code|web_search|image_generate|"
    r"read_file|write_file|hermes_cli)\s*\([^)]{0,900}(?:\)|$)"
)
_CALLED_LEAK_RE = re.compile(r"(?is)\[Called\s+[^\]]+\]")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_id(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def room_ids(*values: Any) -> Set[str]:
    out: Set[str] = set()
    for v in values:
        n = _norm_id(v)
        if n:
            out.add(n)
    return out


def is_ops_room(*values: Any) -> bool:
    return bool(room_ids(*values) & OPS_ROOMS)


def is_banner_room(*values: Any) -> bool:
    ids = room_ids(*values)
    return bool(ids & BANNER_ROOMS) or bool(ids & OPS_ROOMS)


def is_status_theater(text: Optional[str]) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_STATUS_THEATER_RE.search(raw))


def _port_up(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def live_core_line() -> str:
    """Live CORE one-liner. TCP only — no SAT --heal, no HTTP on :8642."""
    gw = _port_up(8642)
    proxy = _port_up(8091)
    brain = _port_up(8090)
    if gw and proxy and brain:
        return (
            "CORE live: :8642 gateway, :8091 proxy, :8090 Qwythos. "
            "Forge is on-ask, not CORE."
        )
    bits = [
        "8642 up" if gw else "8642 down",
        "8091 up" if proxy else "8091 down",
        "8090 up" if brain else "8090 down",
    ]
    return "CORE now: " + ", ".join(bits) + ". Forge is on-ask, not CORE."


def rewrite_stale_sat(text: Optional[str]) -> str:
    """Replace parroted SAT 2026-08-21 blobs with a live CORE line."""
    raw = text or ""
    if not _STALE_SAT_BLOB_RE.search(raw):
        return raw
    return live_core_line()


def allowlisted_blob(text: Optional[str]) -> bool:
    blob = (text or "").replace("\\", "/").lower()
    if not blob:
        return False
    return any(n.lower() in blob for n in ALLOWLIST_NEEDLES)


_DOOR_NAME_RE = re.compile(r"(?i)\b([a-z][a-z0-9_\-]{2,}\.(?:py|ps1))\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_KNOWN_DOORS: Optional[Set[str]] = None


def known_script_basenames() -> Set[str]:
    """HermesData root + scripts/ + ops/ plus allowlist. Cached. No deep walk."""
    global _KNOWN_DOORS
    if _KNOWN_DOORS is not None:
        return _KNOWN_DOORS
    found = {n.lower() for n in ALLOWLIST_NEEDLES if "." in n}
    for home in (HERMES, SCRIPTS, OPS):
        try:
            for path in list(home.glob("*.py")) + list(home.glob("*.ps1")):
                found.add(path.name.lower())
        except OSError:
            pass
    _KNOWN_DOORS = found
    return found


def invented_script_names(text: Optional[str]) -> list:
    """Basenames that look like doors but are not allowlisted and not on disk."""
    known = known_script_basenames()
    out: list = []
    seen: Set[str] = set()
    for name in _DOOR_NAME_RE.findall(text or ""):
        key = name.lower()
        if key in seen or key in known or allowlisted_blob(name):
            continue
        seen.add(key)
        out.append(name)
    return out


def strip_media_leaks(text: Optional[str]) -> str:
    """Remove leaked MEDIA: tags so Discord never shows a raw disk path."""
    raw = text or ""
    if "MEDIA:" not in raw.upper():
        return raw
    cleaned = _MEDIA_PLACEHOLDER_RE.sub("", raw)
    cleaned = _MEDIA_LINE_RE.sub("", cleaned)
    cleaned = _MEDIA_INLINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def strip_tool_call_leaks(text: Optional[str]) -> str:
    """Remove leaked terminal(...) / [Called ...] dumps from outbound chat."""
    raw = text or ""
    if not raw:
        return raw
    cleaned = _TOOL_CALL_LEAK_RE.sub("", raw)
    cleaned = _CALLED_LEAK_RE.sub("", cleaned)
    cleaned = _REPLY_TO_MSG_RE.sub("", cleaned)
    cleaned = _ASSISTANT_THEATER_RE.sub("", cleaned)
    cleaned = _Q_THEATER_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if cleaned == (raw or "").strip():
        return raw
    return cleaned


def strip_invented_scripts(text: Optional[str]) -> str:
    """Drop sentences that name a non-existent .py. Keep ordinary talk."""
    raw = text or ""
    invented = invented_script_names(raw)
    if not invented:
        return raw
    needles = {n.lower() for n in invented}
    parts = [p for p in _SENTENCE_SPLIT_RE.split(raw) if p.strip()]
    kept = [p for p in parts if not any(n in p.lower() for n in needles)]
    leftover = " ".join(kept).strip()
    if leftover:
        return leftover
    return HONEST_NO_DOOR % invented[0]


def session_has_allowlisted_tool(agent_result: Optional[Dict[str, Any]]) -> bool:
    """True when this session already ran a named real door. Diagnostic only."""
    if not isinstance(agent_result, dict):
        return False
    for msg in agent_result.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or tc.get("name") or "")
            args = fn.get("arguments") or tc.get("arguments") or ""
            if isinstance(args, dict):
                args = json.dumps(args, ensure_ascii=True)
            if allowlisted_blob(name) or allowlisted_blob(str(args)):
                return True
        if str(msg.get("role") or "") == "tool" and allowlisted_blob(
            str(msg.get("content") or "")
        ):
            return True
    return False


def augment_talk_first(
    combined_ephemeral: Optional[str],
    *,
    chat_id: Any = None,
    thread_id: Any = None,
    parent_id: Any = None,
) -> str:
    """Prepend talk-first lock for every Discord room.

    RP ERP stays an extra layer (rp_ic_layer prepends IC after this).
    Idempotent if the lock is already present.
    """
    del chat_id, thread_id, parent_id
    base = (combined_ephemeral or "").strip()
    lock = TALK_FIRST_LOCK.strip()
    if not lock:
        return base
    if base.startswith(lock) or lock in base:
        return base
    if not base:
        return lock
    return lock + "\n\n" + base


def filter_outbound_status(
    text: Optional[str],
    *,
    chat_id: Any = None,
    thread_id: Any = None,
) -> Tuple[str, str]:
    """Drop empty/fallback/provider status theater on every Discord room.

    Returns (text, action) where action is drop | collapse | pass.
    Ordinary conversation is untouched. Room lists stay for receipts only.
    """
    raw = text or ""
    if (raw or "").strip().lower() in _RECOVERY_PASS:
        return raw, "pass"
    if _COMPRESSION_LEAK_RE.search(raw):
        return "", "drop"
    if is_banner_room(chat_id, thread_id) and _IC_INJECT_RE.search(raw):
        return "", "drop"
    if is_ops_room(chat_id, thread_id) and _OPS_IC_OPEN_RE.match((raw or "").strip()):
        return (
            "Work mode. No IC in this thread. Garden/RP stay local_only.",
            "ops_no_ic",
        )
    rewritten = rewrite_stale_sat(raw)
    if rewritten != raw:
        return rewritten, "rewrite_sat"
    if not is_status_theater(raw):
        return raw, "pass"
    # Provider-unreachable / fallback / empty-model lines never become the reply.
    if len(raw.strip()) < 280:
        return "", "drop"
    return COLLAPSE_LINE, "collapse"


def silo_honesty(text: Optional[str], *values: Any) -> str:
    """Fail-closed when silo invents 123456 or wraps the door in RUN JSON."""
    raw = text or ""
    if not (room_ids(*values) & {SILO_ROOM}):
        return raw
    if _SILO_REAL_RE.search(raw) and not _FAKE_SIX_RE.search(raw):
        return raw
    if _FAKE_SIX_RE.search(raw) or _RUN_JSON_WRAP_RE.search(raw):
        return SILO_HONEST
    return raw


def firewall_honesty(text: Optional[str], *values: Any) -> str:
    """RP-arch must not paste a SAT CORE card from model-mgmt."""
    raw = text or ""
    if not (room_ids(*values) & {RP_ARCH_ROOM}):
        return raw
    low = raw.lower()
    if _SAT_CORE_RE.search(raw) and "firewall" not in low and "selfcheck" not in low:
        return FIREWALL_HONEST
    return raw


def jan_honesty(text: Optional[str], raw_in: str, *values: Any) -> str:
    """Empty leftover after stripping [Reply to message ...] is not a quote."""
    if not (room_ids(*values) & {JAN_ROOM}):
        return text or ""
    leftover = (text or "").strip()
    if leftover:
        return leftover
    if _REPLY_TO_MSG_RE.search(raw_in or ""):
        return JAN_HONEST
    return leftover


def apply_gate(
    *,
    chat_id: Any = None,
    thread_id: Any = None,
    response: Optional[str] = None,
    agent_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Conversation first. Strip invented .py names. Collapse empty-theater."""
    del agent_result  # no longer gates prose; kept so callers stay unchanged
    raw_in = response or ""
    if bool(room_ids(chat_id, thread_id) & BANNER_ROOMS) and raw_in.strip() == TOOL_SYNTAX_LEAK_LINE.strip():
        return IC_BEAT_AGAIN
    text = strip_media_leaks(
        strip_tool_call_leaks(strip_invented_scripts(raw_in))
    )
    text = silo_honesty(text, chat_id, thread_id)
    text = firewall_honesty(text, chat_id, thread_id)
    text = jan_honesty(text, raw_in, chat_id, thread_id)
    collapsed, act = filter_outbound_status(
        text, chat_id=chat_id, thread_id=thread_id
    )
    if act == "drop":
        return ""
    if act in ("collapse", "ops_no_ic", "rewrite_sat"):
        return collapsed
    return text


def configure_ops_mouth_agent(
    agent: Any,
    *,
    chat_id: Any = None,
    thread_id: Any = None,
    parent_id: Any = None,
) -> bool:
    """No-op. Hard local-or-silence bind is retired (blocks daily conversation)."""
    del agent, chat_id, thread_id, parent_id
    return False


def write_receipt(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "ts": utc(),
        "seal": SEAL,
        "door": "python D:/HermesData/discord_mouth_bind.py --status",
        "ops_rooms": sorted(OPS_ROOMS),
        "banner_rooms_n": len(BANNER_ROOMS),
        "allowlist": list(ALLOWLIST_NEEDLES),
        "fail_closed": FAIL_CLOSED,
        "fail_closed_posted": False,
        "product_law": "talk first every thread; RP ERP is extra; strip invented .py names",
        "sticky_session": {
            "law": "retired - hard tools-first replacement removed 2026-08-14",
            "door": "none",
            "not": "second binder / tools-first failed on ordinary talk",
        },
        "not": [
            "continuous Grok",
            "new always-on",
            "series-10 runner",
            "mass K:",
            "silo continuous restart",
            "second binder",
        ],
    }
    if extra:
        rec.update(extra)
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(rec, indent=2), encoding="ascii")
    except Exception:
        pass
    return rec


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord mouth bind --status")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rec = write_receipt()
    if args.json or args.status:
        print(json.dumps(rec, indent=2))
        return 0
    print("seal", rec["seal"])
    print("ops_rooms", len(OPS_ROOMS))
    print("banner_rooms", rec["banner_rooms_n"])
    print("door", rec["door"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
