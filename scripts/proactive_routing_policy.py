#!/usr/bin/env python3
"""
proactive_routing_policy.py - Classify requests for local-only vs T2 fleet offload.

Local-first invariant (when in doubt, keep local):
  - Roleplay, tools, vault/private paths, PII, HIPAA, explicit, secrets/credentials
    -> local_only (Qwythos @ :8090) -- never free fleet, never paid cloud body
  - Alice depth surfaces (personhood / Just Alice / Millbrook / partner IC)
    -> local_only -- never free nano body, never hard-upgrade under GPU contention
  - Public, non-sensitive research/synthesis with clear intent -> offload_compute (T2/T3)
  - Realtime context that should stay with local voice -> augment_local (existing prefetch)
  - Ambiguous or borderline prompts -> local_first (never guess offload)

Depth tune (alice-depth-tune-v1-2026-08-10): companion/personhood was leaking to free
via local_first + prefer_fleet hard-upgrade. Depth returns local_only so private_modes
blocks hard-upgrade in escalation_router.try_proactive_offload_dispatch.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from escalation_router import is_roleplay_route

ROUTING_LOCAL_ONLY = "local_only"
ROUTING_AUGMENT_LOCAL = "augment_local"
ROUTING_OFFLOAD_COMPUTE = "offload_compute"
ROUTING_LOCAL_FIRST = "local_first"

# Discord surfaces that need Qwythos depth (never free-body, never prefer_fleet upgrade).
# chat_id / thread_id / parent_channel_id match (string compare).
_DEPTH_LOCAL_CHANNEL_IDS = frozenset(
    {
        "1533447417524125796",  # soul forge / personhood
        "1531786894445121648",  # about-me / Jeff interview
        "1525214795236773918",  # Just Alice pure IC
        "1532906132056838184",  # Millbrook pure IC heat wall
        "1519509288286949466",  # Alice RP sandbox parent
        "1521146755985576116",  # narrator / image play (garden)
        "1524821864956956793",  # harem image mod (garden)
        "1523604530338730004",  # Alice RP child
    }
)

# Partner / personhood content markers (channel-agnostic safety net).
_COMPANION_DEPTH_MARKERS = (
    "personhood",
    "soul forge",
    "soul-forge",
    "i missed you",
    "i love you",
    "love you",
    "sit with me",
    "hold me",
    "kiss me",
    "how are we",
    "how are you feeling",
    "our relationship",
    "about us",
    "partner pin",
    "us_now",
    "just alice",
    "millbrook",
    "be with me",
    "come here",
    "cuddle",
    "snuggle",
    "missed you",
    "feel about us",
)

# Local-only law (Jeff): PII / HIPAA / explicit / secrets+credentials never leave Qwythos.
# Free fleet + paid Grok are blocked when any of these fire.
_SENSITIVE_MARKERS = (
    # --- credentials / secrets / auth ---
    "password",
    "passwd",
    "passphrase",
    "api_key",
    "api-key",
    "api key",
    "apikey",
    "access key",
    "access_key",
    "secret",
    "client_secret",
    "client secret",
    "private_key",
    "private key",
    "ssh key",
    "ssh-key",
    "bearer token",
    "auth token",
    "refresh token",
    "oauth token",
    "session token",
    "jwt",
    "credential",
    "credentials",
    "connection string",
    "conn string",
    "database password",
    "db password",
    "smtp password",
    "webhook secret",
    "signing secret",
    "encryption key",
    "master key",
    "service account",
    "service_account",
    ".env",
    "auth.json",
    "bitwarden",
    "1password",
    "lastpass",
    "discord_bot_token",
    "discord token",
    "bot token",
    "grok_api_key",
    "xai_api_key",
    "openrouter_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "groq_api_key",
    "aws_secret",
    "aws_access",
    "azure_client_secret",
    "gcp_service_account",
    # --- PII / identity ---
    "ssn",
    "social security",
    "credit card",
    "card number",
    "cvv",
    "date of birth",
    "date-of-birth",
    "drivers license",
    "driver's license",
    "passport number",
    "bank account",
    "routing number",
    "tax id",
    "ein ",
    # --- HIPAA / health ---
    "medical record",
    "patient chart",
    "patient records",
    "protected health",
    "hipaa",
    "phi ",
    " phi",
    "ephi",
)

_EXPLICIT_MARKERS = (
    "ooc:",
    "bedroom",
    "uncensored",
    "harem",
    "explicit",
    "nsfw",
    "erotic",
    "porn",
    "nude",
    "nudity",
    "xxx",
)

_PRIVATE_PATH_RE = re.compile(
    r"(?i)(?:[d-z]:\\|~/|\./)?(?:phronesisvault|hermesdata|roleplay-sandbox|"
    r"\.env|secrets?\\|auth\.json|credentials?\\)",
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Live credential material (high confidence) -- always local-only
_CREDENTIAL_VALUE_RE = re.compile(
    r"(?ix)"
    r"("
    r"\bsk-[A-Za-z0-9_\-]{16,}\b"  # OpenAI-style
    r"|\bxai-[A-Za-z0-9_\-]{16,}\b"  # xAI
    r"|\bghk_[A-Za-z0-9]{20,}\b"  # GitHub fine-grained
    r"|\bghp_[A-Za-z0-9]{20,}\b"  # GitHub classic
    r"|\bgho_[A-Za-z0-9]{20,}\b"
    r"|\bghu_[A-Za-z0-9]{20,}\b"
    r"|\bglpat-[A-Za-z0-9_\-]{20,}\b"  # GitLab
    r"|\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"  # Slack
    r"|\bAKIA[0-9A-Z]{16}\b"  # AWS access key id
    r"|\bASIA[0-9A-Z]{16}\b"
    r"|\bAIza[0-9A-Za-z_\-]{20,}\b"  # Google API
    r"|\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"  # JWT
    r"|\bBearer\s+[A-Za-z0-9_\-\.=]{16,}\b"
    r"|\b-----BEGIN\s+(?:RSA\s+|OPENSSH\s+|EC\s+|DSA\s+)?PRIVATE\s+KEY-----"
    r")"
)

# assignment-style secrets: KEY=value / token: value
_CREDENTIAL_ASSIGN_RE = re.compile(
    r"(?ix)"
    r"\b("
    r"api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret|"
    r"password|passwd|passphrase|auth[_-]?token|refresh[_-]?token|"
    r"bearer|oauth|session[_-]?token|private[_-]?key|webhook[_-]?secret|"
    r"connection[_-]?string|database[_-]?url|db[_-]?url|"
    r"discord[_-]?token|bot[_-]?token|openrouter[_-]?api[_-]?key|"
    r"openai[_-]?api[_-]?key|xai[_-]?api[_-]?key|groq[_-]?api[_-]?key|"
    r"anthropic[_-]?api[_-]?key|aws[_-]?secret[_-]?access[_-]?key"
    r")\b"
    r"\s*[:=]\s*\S+"
)

# Strong public/ops intents — free OK (grunt thrift).
_PUBLIC_OFFLOAD_INTENTS = (
    "summarize",
    "summary of",
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

# Weak classify intents — free only when not companion-depth and prompt has grunt length.
_WEAK_PUBLIC_INTENTS = (
    "explain",
    "what is",
    "what are",
    "how does",
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
    """True when content must stay on local Qwythos (never free/cloud body).

    Covers: secrets/credentials/API keys, PII, HIPAA, explicit, private paths.
    """
    raw = text or ""
    low = raw.lower()
    # High-confidence credential material first
    if _CREDENTIAL_VALUE_RE.search(raw):
        return True, "credential_material"
    if _CREDENTIAL_ASSIGN_RE.search(raw):
        return True, "credential_assignment"
    for marker in _SENSITIVE_MARKERS:
        if marker in low:
            return True, f"sensitive:{marker}"
    for marker in _EXPLICIT_MARKERS:
        if marker in low:
            return True, f"explicit:{marker}"
    if _PRIVATE_PATH_RE.search(raw):
        return True, "private_path"
    if _EMAIL_RE.search(raw):
        return True, "email_pii"
    if _PHONE_RE.search(raw):
        return True, "phone_pii"
    return False, ""


def is_fleet_safe_for_offload(text: str) -> Tuple[bool, str]:
    """Post-sanitize gate: block fleet dispatch if any private/explicit/secret signal remains."""
    sensitive, reason = contains_sensitive_content(text)
    if sensitive:
        return False, reason
    if _PRIVATE_PATH_RE.search(text or ""):
        return False, "private_path_residual"
    if _CREDENTIAL_VALUE_RE.search(text or "") or _CREDENTIAL_ASSIGN_RE.search(text or ""):
        return False, "credential_residual"
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
    """Strip local identifiers + credentials before free cloud (best-effort).

    Phase 4: prefer privacy_mask_rehydrate.mask_for_offload (handles + rehydrate).
    This function remains one-way redaction for callers that do not keep a map.
    """
    try:
        from privacy_mask_rehydrate import mask_for_offload

        pack = mask_for_offload(prompt or "")
        masked = str(pack.get("masked") or "")
        if masked:
            return masked.strip()
    except Exception:
        pass
    out = prompt or ""
    out = _CREDENTIAL_VALUE_RE.sub("[CREDENTIAL_REDACTED]", out)
    out = _CREDENTIAL_ASSIGN_RE.sub(
        lambda m: re.sub(r"[:=]\s*\S+", "=[CREDENTIAL_REDACTED]", m.group(0), count=1),
        out,
    )
    out = _PRIVATE_PATH_RE.sub("[LOCAL_PATH_REDACTED]", out)
    out = _EMAIL_RE.sub("[EMAIL_REDACTED]", out)
    out = _PHONE_RE.sub("[PHONE_REDACTED]", out)
    out = re.sub(
        r"(?i)\b(?:api[_-]?key|password|passwd|token|secret|credential|bearer)\s*[:=]\s*\S+",
        "[CREDENTIAL_REDACTED]",
        out,
    )
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
    strong = False
    for phrase in _PUBLIC_OFFLOAD_INTENTS:
        if phrase in low:
            matched.append(f"intent:{phrase}")
            strong = True
    weak: List[str] = []
    for phrase in _WEAK_PUBLIC_INTENTS:
        if phrase in low:
            weak.append(f"intent:{phrase}")
    task = str(routing.get("task_type") or "").lower()
    if task in ("research", "web", "summarize"):
        matched.append(f"task_type:{task}")
        strong = True
    if re.search(r"\b(today|this week|202[4-9])\b", low) and any(
        k in low for k in ("news", "ai", "tech", "release", "announce")
    ):
        matched.append("realtime_public_news")
        strong = True
    if strong:
        return True, matched + weak
    # Weak classify alone: free OK only as real grunt (length or classify task).
    if weak:
        if task == "classify" or len((prompt or "").strip()) >= 64:
            return True, weak + ["weak_intent_grunt_ok"]
        return False, []
    return False, matched


def _routing_ids(routing: Optional[Dict[str, Any]]) -> List[str]:
    route = routing or {}
    ids: List[str] = []
    for key in ("chat_id", "thread_id", "parent_channel_id", "channel_id"):
        val = str(route.get(key) or "").strip()
        if val:
            ids.append(val)
    return ids


def depth_local_reason(
    routing: Optional[Dict[str, Any]],
    prompt: str,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Why this turn must stay on Qwythos for companion depth (or None).

    local_only blocks prefer_fleet hard-upgrade in escalation_router (private_modes).
    """
    route = routing or {}
    for cid in _routing_ids(route):
        if cid in _DEPTH_LOCAL_CHANNEL_IDS:
            return f"depth_channel:{cid}"
    model = str(route.get("model") or route.get("request_model") or "").lower()
    if "roleplay" in model or model.endswith("-rp"):
        return "depth_roleplay_model"
    blob = f"{prompt or ''}\n{_message_blob(messages or [])}".lower()
    for marker in _COMPANION_DEPTH_MARKERS:
        if marker in blob:
            return f"depth_marker:{marker}"
    # System/context already carrying personhood pin language
    if "personhood_pin" in blob or "alice_open_loops" in blob:
        return "depth_personhood_context"
    return None


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

    # Alice depth: personhood / Just Alice / Millbrook / partner IC — never free nano body.
    depth_reason = depth_local_reason(routing, prompt or "", messages)
    if depth_reason:
        return {
            "mode": ROUTING_LOCAL_ONLY,
            "eligible": False,
            "reasons": [depth_reason, "alice_depth_local"],
            "sanitized_prompt": prompt,
            "depth_seal": "alice-depth-tune-v1-2026-08-10",
        }

    if _has_tool_context(messages, body):
        return {
            "mode": ROUTING_LOCAL_ONLY,
            "eligible": False,
            "reasons": ["tools_or_local_ops_required"],
            "sanitized_prompt": prompt,
        }

    blob = _message_blob(messages)
    # Phase 4: hard-local (RP/explicit/HIPAA/identity) always; maskable spans may
    # offload only after privacy_mask_rehydrate handle replacement.
    try:
        from privacy_mask_rehydrate import hard_local_reason, prepare_structural_offload
    except Exception:
        hard_local_reason = None  # type: ignore
        prepare_structural_offload = None  # type: ignore

    _MASKABLE_REASONS = frozenset(
        {
            "email_pii",
            "phone_pii",
            "private_path",
            "credential_material",
            "credential_assignment",
        }
    )

    for surface in (blob, prompt or ""):
        if hard_local_reason is not None:
            hard = hard_local_reason(surface, routing=routing)
            if hard:
                return {
                    "mode": ROUTING_LOCAL_ONLY,
                    "eligible": False,
                    "reasons": [hard],
                    "sanitized_prompt": prompt,
                    "privacy_seal": "privacy-mask-rehydrate-v1-2026-08-08",
                }
        sensitive, sens_reason = contains_sensitive_content(surface)
        if sensitive and sens_reason not in _MASKABLE_REASONS:
            # Keyword markers (password, secret, hipaa, explicit, ...) stay local
            return {
                "mode": ROUTING_LOCAL_ONLY,
                "eligible": False,
                "reasons": [sens_reason],
                "sanitized_prompt": prompt,
            }
        # maskable reasons: fall through; offload pack will mask or fail closed

    hdr_route = (headers.get("X-Phronesis-Routing") or headers.get("x-phronesis-routing") or "").strip().lower()
    if hdr_route in ("local", "local-only", "sovereign"):
        return {
            "mode": ROUTING_LOCAL_ONLY,
            "eligible": False,
            "reasons": ["header_force_local"],
            "sanitized_prompt": prompt,
        }

    intent_ok, intent_reasons = _public_offload_intent(prompt, routing)

    def _offload_pack(reasons: List[str]) -> Dict[str, Any]:
        if prepare_structural_offload is not None:
            prep = prepare_structural_offload(prompt or "", routing=routing)
            if not prep.get("allow"):
                return {
                    "mode": ROUTING_LOCAL_ONLY,
                    "eligible": False,
                    "reasons": [prep.get("block_reason") or "offload_blocked", *reasons],
                    "sanitized_prompt": prompt,
                    "privacy_seal": prep.get("seal"),
                }
            return {
                "mode": ROUTING_OFFLOAD_COMPUTE,
                "eligible": True,
                "reasons": reasons,
                "sanitized_prompt": prep.get("fleet_prompt") or prompt,
                "mask_map": prep.get("mask_map") or {},
                "privacy_span_count": prep.get("span_count") or 0,
                "privacy_seal": prep.get("seal"),
            }
        sanitized = sanitize_for_fleet(prompt)
        safe, block_reason = is_fleet_safe_for_offload(sanitized)
        if not safe:
            return {
                "mode": ROUTING_LOCAL_ONLY,
                "eligible": False,
                "reasons": [block_reason, "offload_blocked_unsafe", *reasons],
                "sanitized_prompt": prompt,
            }
        return {
            "mode": ROUTING_OFFLOAD_COMPUTE,
            "eligible": True,
            "reasons": reasons,
            "sanitized_prompt": sanitized,
            "mask_map": {},
        }

    if hdr_route in ("offload", "fleet", "t2"):
        reasons.append("header_force_offload")
        return _offload_pack(reasons)

    if intent_ok:
        if _ambiguous_prompt(prompt, intent_reasons):
            return {
                "mode": ROUTING_LOCAL_FIRST,
                "eligible": False,
                "reasons": ["ambiguous_keep_local"],
                "sanitized_prompt": prompt,
            }
        return _offload_pack(list(intent_reasons))

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