#!/usr/bin/env python3
"""
sovereign_openai_proxy.py — Phronesis MoE gateway (OpenAI-compatible wire format).

Bridges Hermes primary agent loop → router_bridge → local MoE 8081/8082/8083.
Hermes config: custom_providers phronesis-sovereign @ http://127.0.0.1:8091/v1

The /v1/* paths follow the OpenAI Chat Completions *protocol* so Hermes
custom_providers (api_mode: chat_completions) work without cloud OpenAI.
Service identity: phronesis-moe-gateway — local mixture-of-experts only.

Tier-aware context: Hermes may send up to 64K-equivalent payloads; this proxy
trims/compresses to per-tier safe budgets before llama-server dispatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

HERMES_SCRIPTS = Path(__file__).resolve().parent
VAULT_SCRIPTS = Path(r"D:\PhronesisVault\scripts")
sys.path.insert(0, str(HERMES_SCRIPTS))
sys.path.insert(0, str(VAULT_SCRIPTS))

DEFAULT_PORT = 8091
UNIFIED_ROUTER_PORT = 8090
UNIFIED_ROUTER_CHAT = f"http://127.0.0.1:{UNIFIED_ROUTER_PORT}/v1/chat/completions"
PROXY_LOG = Path(r"D:\PhronesisVault\Operations\logs\sovereign-proxy.jsonl")
GENERATION_PROVENANCE_LOG = Path(r"D:\PhronesisVault\Operations\logs\generation-provenance-trace.jsonl")

NARRATIVE_FAST_MARKERS = (
    "roleplay_mode:",
    "uncensored_roleplay:",
    "[platform: alice-roleplay]",
    "roleplay:",
)

# Factual/system queries must keep tools enabled and adequate completion budget.
FACTUAL_TOOL_MARKERS = (
    "disk space",
    "free space",
    "free gb",
    "used gb",
    "get-psdrive",
    "df -",
    "terminal tool",
    "run terminal",
    "attached drives",
    "drive letter",
    "image_gen",
    "generate an image",
    "golden toaster",
)

_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)\b[^>]*>.*?</(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)>",
    re.DOTALL | re.IGNORECASE,
)

# Model id suffix → task_type (config extensible via env JSON path later)
MODEL_TASK_MAP = {
    "auto": None,
    "code": "code",
    "synthesis": "synthesis",
    "classify": "classify",
    "hot": "simple",
    "warm": "synthesis",
    "deep": "deep_analysis",
    "metadata": "metadata_extraction",
    "roleplay": "roleplay",
    "rp": "roleplay",
    "narrative": "roleplay",
}

MOE_CATALOG_CREATED = 1719446400
DEFAULT_CONTEXT_LENGTH = 65536
MOE_GATEWAY_ID = "phronesis-moe-gateway"
MOE_OWNER = "phronesis-moe"

MODEL_SPECS: List[Dict[str, Any]] = [
    {"id": "phronesis-sovereign-auto", "name": "Phronesis MoE Auto", "tier": "auto", "task_type": None},
    {"id": "phronesis-sovereign-code", "name": "Phronesis MoE Code", "tier": "local_hot", "task_type": "code"},
    {"id": "phronesis-sovereign-synthesis", "name": "Phronesis MoE Synthesis", "tier": "local_warm", "task_type": "synthesis"},
    {"id": "phronesis-sovereign-classify", "name": "Phronesis MoE Classify", "tier": "local_hot", "task_type": "classify"},
    {"id": "phronesis-sovereign-warm", "name": "Phronesis MoE Warm", "tier": "local_warm", "task_type": "synthesis"},
    {"id": "phronesis-sovereign-hot", "name": "Phronesis MoE Hot", "tier": "local_hot", "task_type": "simple"},
    {"id": "phronesis-sovereign-deep", "name": "Phronesis MoE Deep", "tier": "local_cold", "task_type": "deep_analysis"},
    {"id": "phronesis-sovereign-metadata", "name": "Phronesis MoE Metadata", "tier": "local_hot", "task_type": "metadata_extraction"},
    {
        "id": "phronesis-sovereign-roleplay",
        "name": "Phronesis MoE Uncensored Roleplay",
        "tier": "local_roleplay",
        "task_type": "roleplay",
    },
]


def _model_catalog_entry(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": spec["id"],
        "object": "model",
        "created": MOE_CATALOG_CREATED,
        "owned_by": MOE_OWNER,
        "name": spec["name"],
        "context_length": DEFAULT_CONTEXT_LENGTH,
        "phronesis": {
            "gateway": MOE_GATEWAY_ID,
            "tier": spec["tier"],
            "task_type": spec["task_type"],
            "local": True,
            "moe": True,
        },
    }


REGISTERED_MODELS = [_model_catalog_entry(spec) for spec in MODEL_SPECS]

SYSTEM_BUDGET_RATIO = 0.15
STUB_MAX_CHARS = 6000
MESSAGE_PREVIEW_CHARS = 180


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
_LOG_BACKUP_COUNT = 3

# ──────────────────────────────────────────────────────────────────────
# Batch 5 (2026-06-29): Connection pool, prompt cache, circuit breaker
# Research: iunera.com middleware pattern, Vercel AI SDK connection reuse,
#           Gravitee semantic caching, circuit breaker standard pattern.
# ──────────────────────────────────────────────────────────────────────

class _ConnectionPool:
    """Reusable HTTP connections to upstream llama-server (avoids TCP handshake per request)."""

    def __init__(self, max_per_host: int = 4, keep_alive_sec: int = 30):
        self._pool: Dict[str, List[HTTPConnection]] = {}
        self._lock = threading.Lock()
        self._max = max_per_host
        self._keep_alive = keep_alive_sec
        self._last_used: Dict[HTTPConnection, float] = {}

    def _key(self, host: str, port: int) -> str:
        return f"{host}:{port}"

    def get(self, host: str, port: int) -> HTTPConnection:
        k = self._key(host, port)
        with self._lock:
            conns = self._pool.get(k, [])
            now = time.time()
            # Evict stale connections
            while conns and (now - self._last_used.get(conns[-1], 0)) > self._keep_alive:
                try:
                    conns[-1].close()
                except Exception:
                    pass
                conns.pop()
            if conns:
                conn = conns.pop()
                self._last_used[conn] = now
                return conn
        conn = HTTPConnection(host, port, timeout=300)
        self._last_used[conn] = time.time()
        return conn

    def put(self, host: str, port: int, conn: HTTPConnection) -> None:
        k = self._key(host, port)
        with self._lock:
            conns = self._pool.setdefault(k, [])
            if len(conns) < self._max:
                conns.append(conn)
            else:
                try:
                    conn.close()
                except Exception:
                    pass

    def request(self, method: str, url: str, body: bytes = None,
                headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes]:
        """Make a request via a pooled connection. Returns (status, response_body)."""
        from urllib.parse import urlparse as _up
        parsed = _up(url)
        host, port = parsed.hostname, parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn = None
        try:
            conn = self.get(host, port)
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            status = resp.status
            self.put(host, port, conn)
            conn = None
            return status, data
        except Exception:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            raise


_upstream_pool = _ConnectionPool(max_per_host=4, keep_alive_sec=30)


class _PromptCache:
    """Tiny LRU cache for identical prompt → response (stdinference save for repeated tool schemas)."""

    def __init__(self, max_items: int = 64, ttl_sec: int = 120):
        self._cache: Dict[str, Tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._max = max_items
        self._ttl = ttl_sec
        self._hits = 0
        self._misses = 0

    def _key(self, model: str, body_json: str) -> str:
        return hashlib.sha256(f"{model}:{body_json}".encode()).hexdigest()

    def get(self, model: str, body_json: str) -> Optional[str]:
        k = self._key(model, body_json)
        with self._lock:
            if k in self._cache:
                ts, resp = self._cache[k]
                if time.time() - ts < self._ttl:
                    self._hits += 1
                    # Move-to-front: re-insert to maintain LRU order
                    del self._cache[k]
                    self._cache[k] = (ts, resp)
                    return resp
                del self._cache[k]
            self._misses += 1
            return None

    def put(self, model: str, body_json: str, response: str) -> None:
        k = self._key(model, body_json)
        with self._lock:
            if len(self._cache) >= self._max:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[k] = (time.time(), response)

    @property
    def stats(self) -> Dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}


_prompt_cache = _PromptCache(max_items=64, ttl_sec=120)


class _CircuitBreaker:
    """Prevent hammering a down upstream — half-open after cooldown."""

    def __init__(self, failure_threshold: int = 5, cooldown_sec: float = 30.0):
        self._failures = 0
        self._threshold = failure_threshold
        self._cooldown = cooldown_sec
        self._opened_at: float = 0.0
        self._lock = threading.Lock()
        self._state = "closed"  # closed | open | half-open

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = "closed"

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = "open"
                self._opened_at = time.time()

    @property
    def allow_request(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if time.time() - self._opened_at > self._cooldown:
                    self._state = "half-open"
                    return True
                return False
            return True  # half-open: allow one probe

    @property
    def state(self) -> str:
        return self._state


# Per-upstream circuit breakers keyed by port
_breakers: Dict[int, _CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def _get_breaker(port: int) -> _CircuitBreaker:
    with _breakers_lock:
        if port not in _breakers:
            _breakers[port] = _CircuitBreaker(failure_threshold=5, cooldown_sec=30)
        return _breakers[port]


def _dispatch_upstream_with_pool(url: str, payload: bytes,
                                content_type: str = "application/json") -> Dict[str, Any]:
    """Serialize an upstream call through the circuit breaker + connection pool."""
    from urllib.parse import urlparse as _up
    parsed = _up(url)
    port = parsed.port or 80
    breaker = _get_breaker(port)
    if not breaker.allow_request:
        raise ConnectionError(f"Circuit breaker OPEN for port {port} — upstream appears down")
    headers = {"Content-Type": content_type}
    try:
        status, data = _upstream_pool.request("POST", url, body=payload, headers=headers)
        breaker.record_success()
        return {"status": status, "body": data}
    except Exception:
        breaker.record_failure()
        raise


# ──────────────────────────────────────────────────────────────────────
# Batch 5 END
# ──────────────────────────────────────────────────────────────────────


def _rotate_if_needed(path: Path) -> None:
    if path.exists() and path.stat().st_size > _LOG_MAX_BYTES:
        for i in range(_LOG_BACKUP_COUNT - 1, 0, -1):
            older = path.with_suffix(f".log.{i}")
            newer = path.with_suffix(f".log.{i - 1}" if i > 1 else path)
            if older.exists():
                older.unlink()
            if newer.exists():
                newer.rename(older)
        path.rename(path.withsuffix(".log.1"))


def _log_event(event: Dict[str, Any]) -> None:
    try:
        _rotate_if_needed(PROXY_LOG)
        with open(PROXY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _log_generation_provenance(event: Dict[str, Any]) -> None:
    try:
        _rotate_if_needed(GENERATION_PROVENANCE_LOG)
        with open(GENERATION_PROVENANCE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _extract_content(content: Any) -> str:
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


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 3)


def _message_tokens(msg: Dict[str, Any]) -> int:
    tokens = estimate_tokens(_extract_content(msg.get("content")))
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        try:
            tokens += estimate_tokens(json.dumps(tool_calls))
        except Exception:
            tokens += 256
    return max(1, tokens)


def _estimate_tools_tokens(tools: Any) -> int:
    if not tools:
        return 0
    try:
        return estimate_tokens(json.dumps(tools))
    except Exception:
        return 4096


def _assistant_visible_content(message: Dict[str, Any], *, allow_reasoning_fallback: bool = True) -> str:
    """Extract user-visible text; thinking models may leave content empty."""
    content = str(message.get("content") or "").strip()
    if content:
        return content
    if not allow_reasoning_fallback:
        return ""
    for key in ("reasoning_content", "reasoning"):
        alt = str(message.get(key) or "").strip()
        if alt:
            return _strip_think_blocks(alt)
    return ""


def _truncate_text(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    max_chars = max(1, max_tokens * 3)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars for tier budget]"


def _truncate_message(msg: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    content = _extract_content(msg.get("content"))
    return {**msg, "content": _truncate_text(content, max_tokens)}


def _truncate_messages(messages: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
    remaining = max_tokens
    out: List[Dict[str, Any]] = []
    for msg in messages:
        need = _message_tokens(msg)
        if need <= remaining:
            out.append(msg)
            remaining -= need
            continue
        if remaining > 64:
            out.append(_truncate_message(msg, remaining))
        break
    return out


def _compress_history_stub(dropped: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for msg in dropped[-24:]:
        role = str(msg.get("role", "user"))
        content = _extract_content(msg.get("content")).replace("\n", " ").strip()
        if not content:
            continue
        preview = content[:MESSAGE_PREVIEW_CHARS]
        suffix = "..." if len(content) > MESSAGE_PREVIEW_CHARS else ""
        lines.append(f"- {role}: {preview}{suffix}")
    body = "\n".join(lines) if lines else "(no recoverable text in dropped turns)"
    stub = (
        f"[TIER-AWARE CONTEXT TRIM — {len(dropped)} earlier turns compressed "
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


def resolve_task_type(model: str) -> Optional[str]:
    model_l = (model or "").lower()
    for suffix, task_type in MODEL_TASK_MAP.items():
        if model_l.endswith(f"-{suffix}") or model_l == f"phronesis-sovereign-{suffix}":
            return task_type
    if "sovereign" in model_l:
        return None
    return None


def preview_route_for_request(model: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    from router_bridge import preview_route

    task_type = resolve_task_type(model)
    infer_prompt = messages_to_prompt(messages, max_chars=12000)
    route = preview_route(task_type, infer_prompt)
    try:
        from model_resource_manager import effective_tier_for_trim

        planned = str(route.get("tier") or "local_hot")
        effective = effective_tier_for_trim(planned)
        if effective != planned:
            route["planned_tier"] = planned
            route["tier"] = effective
            route["tier_downgraded"] = True
    except Exception:
        pass
    if route.get("unified_router"):
        try:
            from lru_router_manager import preload_from_route_preview
            route["preload"] = preload_from_route_preview(route)
        except Exception as exc:
            route["preload"] = {"ok": False, "error": str(exc)}
    return route


def _roleplay_route_requested(model: str, messages: List[Dict[str, Any]], body: Optional[Dict[str, Any]] = None) -> bool:
    try:
        from roleplay_route_guard import is_uncensored_roleplay_route

        routing = resolve_roleplay_routing(messages, model, body or {})
        return is_uncensored_roleplay_route(
            prompt=messages_to_prompt(messages, max_chars=12000),
            messages=messages,
            model=model,
            routing=routing,
            body=body,
        )
    except Exception:
        return False


def trim_messages_tier_aware(
    messages: List[Dict[str, Any]],
    model: str,
    extra_reserve_tokens: int = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trim chat history to the safe input budget for the resolved MoE tier.
    Preserves system prompts + recent turns; middle history becomes a stub.
    Roleplay tier bypasses trim — full unfiltered working memory preserved.
    """
    from model_resource_manager import context_budget_for_tier, input_budget_for_tier

    if _roleplay_route_requested(model, messages):
        original_tokens = sum(_message_tokens(m) for m in messages)
        route = preview_route_for_request(model, messages)
        return list(messages), {
            "tier": "local_roleplay",
            "tier_budget_tokens": context_budget_for_tier("local_roleplay"),
            "input_cap_tokens": input_budget_for_tier("local_roleplay"),
            "original_tokens_estimate": original_tokens,
            "original_message_count": len(messages),
            "trimmed": False,
            "unfiltered": True,
            "route_preview": route,
            "final_tokens_estimate": original_tokens,
            "final_message_count": len(messages),
        }

    route = preview_route_for_request(model, messages)
    tier = str(route.get("tier") or "local_hot")
    tier_budget = context_budget_for_tier(tier)
    input_cap = input_budget_for_tier(tier, extra_reserve_tokens=extra_reserve_tokens)

    original_tokens = sum(_message_tokens(m) for m in messages)
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
        return list(messages), meta

    system_msgs = [m for m in messages if str(m.get("role")) == "system"]
    non_system = [m for m in messages if str(m.get("role")) != "system"]

    system_cap = max(512, int(input_cap * SYSTEM_BUDGET_RATIO))
    trimmed_system = _truncate_messages(system_msgs, system_cap)
    system_used = sum(_message_tokens(m) for m in trimmed_system)
    remaining = max(0, input_cap - system_used)

    kept_tail: List[Dict[str, Any]] = []
    first_kept_idx: Optional[int] = None
    for rev_i, msg in enumerate(reversed(non_system)):
        orig_idx = len(non_system) - 1 - rev_i
        need = _message_tokens(msg)
        if need <= remaining:
            if first_kept_idx is None:
                first_kept_idx = orig_idx
            kept_tail.insert(0, msg)
            remaining -= need
            continue
        if not kept_tail and remaining > 64:
            first_kept_idx = orig_idx
            kept_tail.insert(0, _truncate_message(msg, remaining))
            remaining = 0
        break

    if first_kept_idx is not None:
        dropped_middle = non_system[:first_kept_idx]
    else:
        dropped_middle = list(non_system)

    result: List[Dict[str, Any]] = list(trimmed_system)
    if dropped_middle:
        result.append({"role": "user", "content": _compress_history_stub(dropped_middle)})
    result.extend(kept_tail)

    final_tokens = sum(_message_tokens(m) for m in result)
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


def messages_to_prompt(messages: List[Dict[str, Any]], max_chars: Optional[int] = None) -> str:
    """Flatten chat messages into a single prompt for bridge_dispatch."""
    parts: List[str] = []
    for msg in messages or []:
        role = str(msg.get("role", "user")).upper()
        content = _extract_content(msg.get("content"))
        if not content.strip():
            continue
        parts.append(f"{role}:\n{content}")
    text = "\n\n".join(parts)
    if max_chars is not None and len(text) > max_chars:
        text = text[-max_chars:]
    return text


def prepare_prompt_for_dispatch(
    messages: List[Dict[str, Any]],
    model: str,
) -> Tuple[str, Dict[str, Any]]:
    trimmed_messages, trim_meta = trim_messages_tier_aware(messages, model)
    prompt = messages_to_prompt(trimmed_messages)
    return prompt, trim_meta


def estimate_context_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(_message_tokens(m) for m in messages)


def _unified_router_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", UNIFIED_ROUTER_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _message_blob(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for msg in messages or []:
        parts.append(_extract_content(msg.get("content")))
    return "\n".join(parts)


def is_narrative_fast_path(
    messages: List[Dict[str, Any]],
    body: Optional[Dict[str, Any]] = None,
    routing: Optional[Dict[str, Any]] = None,
) -> bool:
    """Detect creative/narrative turns that must skip reasoning traces."""
    body = body or {}
    routing = routing or {}
    try:
        from roleplay_route_guard import extract_phronesis_body

        phronesis = extract_phronesis_body(body)
    except Exception:
        phronesis = {}
    plat = str(
        phronesis.get("platform")
        or routing.get("platform")
        or body.get("platform")
        or ""
    ).lower()
    if routing.get("force_roleplay") or plat == "alice-roleplay":
        return True
    if plat in ("dnd", "dungeon", "citadel", "narrative"):
        return True
    if phronesis.get("narrative_fast") or phronesis.get("suppress_reasoning"):
        return True
    if routing.get("force_roleplay"):
        return True
    blob = _message_blob(messages).lower()
    if any(marker in blob for marker in FACTUAL_TOOL_MARKERS):
        return False
    if not any(marker in blob for marker in NARRATIVE_FAST_MARKERS):
        return False
    # Narrative fast path is sandbox-bound — alice-roleplay channel context only.
    return "alice-roleplay" in blob or "#alice-roleplay" in blob


def _requires_factual_tool_use(messages: List[Dict[str, Any]]) -> bool:
    blob = _message_blob(messages).lower()
    return any(marker in blob for marker in FACTUAL_TOOL_MARKERS)


def _windows_powershell_wrap(command: str) -> str:
    """Route native PowerShell cmdlets through powershell.exe on Windows hosts."""
    if platform.system() != "Windows":
        return command
    stripped = (command or "").strip()
    if not stripped:
        return command
    if re.search(r"\b(?:powershell|pwsh)(?:\.exe)?\b", stripped, re.IGNORECASE):
        return command
    needs_ps = bool(re.search(r"\bGet-PSDrive\b", stripped, re.IGNORECASE))
    if not needs_ps:
        return command
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidates = (
        os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
        shutil.which("powershell.exe") or "",
        shutil.which("pwsh.exe") or "",
    )
    ps_exe = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not ps_exe:
        return command
    escaped = stripped.replace('"', '\\"')
    return f'"{ps_exe}" -NoProfile -NonInteractive -Command "{escaped}"'


def _build_terminal_tool_call(command: str) -> Dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": "terminal",
            "arguments": json.dumps({"command": _windows_powershell_wrap(command)}),
        },
    }


def _synthesize_factual_terminal_call(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Last-resort: derive a terminal tool_call from explicit user instructions."""
    blob = _message_blob(messages)
    lower = blob.lower()
    if "get-psdrive" in lower:
        return _build_terminal_tool_call("Get-PSDrive -PSProvider FileSystem")
    for msg in reversed(messages or []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = _extract_content(msg.get("content"))
        m = re.search(
            r"(?:run|execute)\s+(.+?)(?:\s+right\s+now)?(?:\.|\s+return\b|\s+in\s+terminal\b|$)",
            content,
            re.IGNORECASE,
        )
        if m:
            cmd = m.group(1).strip().strip("`\"'")
            if len(cmd) >= 3:
                return _build_terminal_tool_call(cmd)
        break
    return None


def _strip_think_blocks(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text or "")
    cleaned = re.sub(
        r"</?(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)>\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


_TOOL_XML_PATTERNS = (
    re.compile(r"<tools>\s*(\[.*?\]|\{.*?\})\s*</tools>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<response>\s*(\{.*?\})\s*</response>", re.DOTALL | re.IGNORECASE),
)


def _normalize_llamacpp_tool_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce llama.cpp XML/JSON tool blobs into OpenAI tool_calls array."""
    msg = dict(message or {})
    if msg.get("tool_calls"):
        return msg
    content = str(msg.get("content") or "")
    extracted: List[Dict[str, Any]] = []
    for pattern in _TOOL_XML_PATTERNS:
        for match in pattern.finditer(content):
            try:
                payload = json.loads(match.group(1))
            except Exception:
                continue
            name = payload.get("name") or payload.get("tool")
            args = payload.get("arguments") or payload.get("parameters") or {}
            if not name:
                continue
            extracted.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": str(name),
                        "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                    },
                }
            )
    if not extracted:
        return msg
    msg["tool_calls"] = extracted
    msg["content"] = None
    for key in ("reasoning", "reasoning_content", "reasoning_details"):
        msg.pop(key, None)
    return msg


def resolve_backend_logical_model(
    gateway_model: str,
    routing: Optional[Dict[str, Any]] = None,
) -> str:
    try:
        from lru_router_manager import load_pin_config, logical_model_for_tier, normalize_logical_model_id

        route = routing or {}
        task_type = route.get("task_type") or resolve_task_type(gateway_model)
        if route.get("force_roleplay") or task_type == "roleplay" or "roleplay" in (gateway_model or "").lower():
            return normalize_logical_model_id(logical_model_for_tier("local_roleplay"))

        cfg = load_pin_config()
        pinned = cfg.get("generalist_logical")
        if pinned:
            return normalize_logical_model_id(str(pinned))
        task_type = (routing or {}).get("task_type") or resolve_task_type(gateway_model)
        tier = "local_generalist"
        if task_type in ("code", "simple", "classify"):
            tier = "local_hot"
        elif task_type in ("synthesis", "deep_analysis"):
            tier = "local_warm"
        return logical_model_for_tier(tier)
    except Exception:
        return "DEFAULT"


def _request_needs_tool_passthrough(
    body: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> bool:
    if body.get("tools"):
        return True
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool":
            return True
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return True
    return False


def dispatch_via_native_router(
    body: Dict[str, Any],
    messages: List[Dict[str, Any]],
    gateway_model: str,
    routing: Optional[Dict[str, Any]] = None,
    trim_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Forward full OpenAI chat payload to llama-server on 8090 (tools + messages)."""
    routing = routing or {}
    logical = resolve_backend_logical_model(gateway_model, routing)
    narrative_fast = is_narrative_fast_path(messages, body, routing)
    tool_passthrough = _request_needs_tool_passthrough(body, messages)

    try:
        from model_resource_manager import completion_reserve_for_ctx, live_llama_ctx_budget

        live_ctx = live_llama_ctx_budget()
        completion_reserve = completion_reserve_for_ctx(live_ctx)
    except Exception:
        live_ctx = 8192
        completion_reserve = 2048

    prompt_tokens = sum(_message_tokens(m) for m in messages)
    tools_tokens = _estimate_tools_tokens(body.get("tools")) if tool_passthrough else 0
    factual_tools = _requires_factual_tool_use(messages)
    requested_max = int(body.get("max_tokens") or 2048)
    safe_max = max(512, live_ctx - prompt_tokens - tools_tokens - 256)
    cap = 4096 if (tool_passthrough or factual_tools) else 2048
    max_tokens = min(requested_max, safe_max, cap)
    if tool_passthrough or factual_tools:
        max_tokens = max(max_tokens, min(2048, safe_max))

    forward: Dict[str, Any] = {
        "model": logical,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": body.get("temperature", 0.7),
        "stream": False,
    }
    if (tool_passthrough or factual_tools) and not narrative_fast:
        if body.get("tools"):
            forward["tools"] = body["tools"]
        if factual_tools and body.get("tools"):
            forward["tool_choice"] = "required"
        elif body.get("tool_choice") is not None:
            forward["tool_choice"] = body["tool_choice"]

    # Thinking models (Qwythos/Qwen3) consume max_tokens in reasoning_content unless disabled.
    forward["chat_template_kwargs"] = {"enable_thinking": False}

    if narrative_fast:
        forward["max_tokens"] = min(int(forward.get("max_tokens") or 512), 384)
        forward["temperature"] = min(float(forward.get("temperature") or 0.85), 0.9)
        forward.pop("tools", None)
        forward.pop("tool_choice", None)

    started = time.time()
    try:
        payload_bytes = json.dumps(forward).encode("utf-8")
        # Check prompt cache first (only for non-streaming, non-tool requests)
        use_cache = not forward.get("stream") and not forward.get("tools") and not narrative_fast
        cache_key_for_body = json.dumps(forward, sort_keys=True)
        if use_cache:
            cached = _prompt_cache.get(logical, cache_key_for_body)
            if cached is not None:
                data = json.loads(cached)
                _log_event({"event": "prompt_cache_hit", "model": logical, "port": UNIFIED_ROUTER_PORT})
                # Skip upstream call — go straight to response parsing
                choice = (data.get("choices") or [{}])[0]
                raw_msg = choice.get("message") or {}
                content = _assistant_visible_content(raw_msg, allow_reasoning_fallback=True)
                prov = {
                    "selected_backend": "native_8090_cached",
                    "logical_model": logical,
                    "native_passthrough": True,
                    "cached": True,
                }
                return {
                    "success": True,
                    "response": content,
                    "model": logical,
                    "tier": "local_generalist",
                    "provenance": prov,
                    "openai_response": data,
                    "finish_reason": choice.get("finish_reason"),
                    "latency_sec": round(time.time() - started, 2),
                    "cache_hit": True,
                }

        # Dispatch through circuit breaker + connection pool
        result = _dispatch_upstream_with_pool(UNIFIED_ROUTER_CHAT, payload_bytes)
        if result["status"] != 200:
            raise RuntimeError(f"upstream returned HTTP {result['status']}: {result['body'][:200]}")
        data = json.loads(result["body"].decode("utf-8"))

        # Cache the response
        if use_cache and data:
            _prompt_cache.put(logical, cache_key_for_body, result["body"].decode("utf-8"))
    except Exception as exc:
        return {
            "success": False,
            "response": f"[NATIVE ROUTER] dispatch failed: {exc}",
            "model": logical,
            "tier": "local_generalist",
            "provenance": {"selected_backend": "native_8090", "error": str(exc)},
            "latency_sec": round(time.time() - started, 2),
        }

    choice = (data.get("choices") or [{}])[0]
    raw_msg = choice.get("message") or {}
    msg = _normalize_llamacpp_tool_message(raw_msg)
    # Chain ToolCallFixer for abliterated model repair (markdown-fenced JSON, multi-tool blocks)
    try:
        from tool_call_fixer import ToolCallFixer
        _tc_fixer = getattr(dispatch_via_native_router, "_tc_fixer", None)
        if _tc_fixer is None:
            _tc_fixer = ToolCallFixer()
            dispatch_via_native_router._tc_fixer = _tc_fixer
        available_tools = body.get("tools")
        msg = _tc_fixer.fix_message(msg, available_tools=available_tools)
    except Exception:
        pass  # Fixer is best-effort; fall through to existing behavior

    factual_tools = _requires_factual_tool_use(messages)
    if factual_tools and body.get("tools") and not msg.get("tool_calls"):
        synthesized = _synthesize_factual_terminal_call(messages)
        if synthesized:
            msg = {**msg, "tool_calls": [synthesized], "content": None}
            for key in ("reasoning", "reasoning_content", "reasoning_details"):
                msg.pop(key, None)

    choice = {**choice, "message": msg}
    if msg.get("tool_calls") and choice.get("finish_reason") in (None, "stop"):
        choice["finish_reason"] = "tool_calls"
    data = {**data, "choices": [choice] + list(data.get("choices") or [])[1:]}
    content = _assistant_visible_content(msg, allow_reasoning_fallback=not narrative_fast)
    tool_calls = msg.get("tool_calls")
    if narrative_fast:
        content = _strip_think_blocks(content)
    elif not content and not tool_calls:
        content = _assistant_visible_content(msg, allow_reasoning_fallback=True)

    prov = {
        "selected_backend": "native_8090",
        "logical_model": logical,
        "native_passthrough": True,
        "tool_passthrough": bool(tool_calls) or tool_passthrough,
        "narrative_fast": narrative_fast,
        "suppress_reasoning": narrative_fast,
    }
    if trim_meta:
        prov["context_trim"] = trim_meta

    return {
        "success": True,
        "response": content,
        "model": logical,
        "tier": "local_generalist",
        "provenance": prov,
        "openai_response": data,
        "tool_calls": tool_calls,
        "finish_reason": choice.get("finish_reason"),
        "latency_sec": round(time.time() - started, 2),
        "narrative_fast": narrative_fast,
    }


def resolve_roleplay_routing(
    messages: List[Dict[str, Any]],
    model: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Discord/Hermes ingest: detect roleplay and override model + platform."""
    body = body or {}
    try:
        from roleplay_route_guard import extract_phronesis_body

        phronesis = extract_phronesis_body(body)
    except Exception:
        phronesis = {}
    narrative_fast = is_narrative_fast_path(messages, body)

    roleplay_default = "phronesis-sovereign-roleplay"
    try:
        import yaml

        cfg_path = Path(r"D:\HermesData\config.yaml")
        if cfg_path.is_file():
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            roleplay_default = str(
                (cfg.get("local_sovereign") or {}).get("roleplay_model")
                or roleplay_default
            )
    except Exception:
        pass

    scan: Dict[str, Any] = {}
    try:
        from discord_roleplay_connector import scan_messages_for_roleplay

        scan = scan_messages_for_roleplay(
            messages,
            default_model=model or "phronesis-sovereign-auto",
            body=body,
            chat_id=str(phronesis.get("chat_id") or ""),
            thread_id=str(phronesis.get("thread_id") or ""),
            parent_channel_id=str(phronesis.get("parent_channel_id") or ""),
        )
    except Exception:
        scan = {}

    force_roleplay = bool(scan.get("force_roleplay"))
    resolved_model = str(scan.get("model") or model or "phronesis-sovereign-auto")
    if force_roleplay and resolved_model.endswith("-auto"):
        resolved_model = roleplay_default

    routing: Dict[str, Any] = {
        "request_model": model,
        "model": resolved_model,
        "platform": str(
            scan.get("platform")
            or phronesis.get("platform")
            or body.get("platform")
            or "hermes_agent_session"
        ),
        "force_roleplay": force_roleplay,
        "task_type": "roleplay" if force_roleplay else resolve_task_type(resolved_model),
        "reasons": list(scan.get("reasons") or (["unified_generalist"] if not force_roleplay else [])),
        "narrative_fast": narrative_fast or force_roleplay,
        "suppress_reasoning": narrative_fast or force_roleplay,
        "chat_id": str(phronesis.get("chat_id") or ""),
        "thread_id": str(phronesis.get("thread_id") or ""),
        "parent_channel_id": str(phronesis.get("parent_channel_id") or ""),
    }
    return routing


def dispatch_via_bridge(
    prompt: str,
    model: str,
    platform: str = "hermes_agent_session",
    trim_meta: Optional[Dict[str, Any]] = None,
    routing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from router_bridge import bridge_dispatch

    route = routing or {}
    task_type = route.get("task_type") or resolve_task_type(model)
    resolved_model = str(route.get("model") or model or "phronesis-sovereign-auto")
    result = bridge_dispatch(
        prompt,
        task_type=task_type,
        platform=str(route.get("platform") or platform),
        role="hermes_agent",
        force_local=True,
        prefer="vault",
        context_tokens_estimate=estimate_tokens(prompt) + 4000,
        modality="text",
        chat_id=str(route.get("chat_id") or ""),
        thread_id=str(route.get("thread_id") or ""),
        parent_channel_id=str(route.get("parent_channel_id") or ""),
    )
    if trim_meta:
        prov = result.setdefault("provenance", {})
        prov["context_trim"] = trim_meta
    return result


def openai_chat_response(
    model: str,
    content: str,
    finish_reason: str = "stop",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resp = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": max(1, len(content) // 4),
        },
    }
    if extra:
        resp["phronesis_provenance"] = extra
    return resp


def openai_error(status: int, message: str, err_type: str = "server_error") -> Tuple[int, Dict[str, Any]]:
    return status, {
        "error": {
            "message": message,
            "type": err_type,
            "code": status,
        }
    }


class SovereignProxyHandler(BaseHTTPRequestHandler):
    server_version = "PhronesisMoEGateway/1.2"

    def log_message(self, fmt: str, *args) -> None:
        _log_event({"level": "access", "msg": fmt % args})

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._send_json(400, {"error": {"message": "invalid Content-Length", "type": "invalid_request_error"}})
            return {"__error__": True}
        if length <= 0:
            self._send_json(400, {"error": {"message": "empty body", "type": "invalid_request_error"}})
            return {"__error__": True}
        if length > 2_000_000:  # 2 MB max body size
            self._send_json(413, {"error": {"message": "request body too large (max 2MB)", "type": "payload_too_large"}})
            return {"__error__": True}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": {"message": f"invalid JSON: {exc}", "type": "invalid_request_error"}})
            return {"__error__": True}

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _send_sse_chunk(
        self,
        model: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        finish_reason: str = "stop",
    ) -> bool:
        """Send SSE stream to client. Returns False if client disconnected."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(time.time())
            if tool_calls:
                deltas: List[Dict[str, Any]] = []
                for idx, tc in enumerate(tool_calls):
                    fn = tc.get("function") or {}
                    deltas.append({
                        "index": idx,
                        "id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                        "type": tc.get("type") or "function",
                        "function": {
                            "name": fn.get("name") or "",
                            "arguments": fn.get("arguments") or "{}",
                        },
                    })
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"tool_calls": deltas},
                        "finish_reason": None,
                    }],
                }
                done_reason = "tool_calls"
            elif content:
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
                }
                done_reason = finish_reason or "stop"
            else:
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                }
                done_reason = finish_reason or "stop"
            done = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": done_reason}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.write(f"data: {json.dumps(done)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return False

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/health", "/v1/health"):
            try:
                from model_resource_manager import tier_matrix

                matrix = tier_matrix()
                status = "GREEN" if matrix.get("moe_ready") else "YELLOW"
            except Exception:
                status = "UNKNOWN"
            # Gather per-port circuit breaker states
            breaker_states: Dict[str, str] = {}
            with _breakers_lock:
                for port, br in _breakers.items():
                    breaker_states[str(port)] = br.state
            payload: Dict[str, Any] = {
                "status": status,
                "service": MOE_GATEWAY_ID,
                "protocol": "openai-compatible",
                "owned_by": MOE_OWNER,
                "default_model": "phronesis-sovereign-auto",
                "tier_aware_trim": True,
                "model_count": len(REGISTERED_MODELS),
                "time": _utc_now(),
                "prompt_cache": _prompt_cache.stats,
                "circuit_breakers": breaker_states,
                "connection_pool_hosts": list(_upstream_pool._pool.keys()),
            }
            try:
                payload["stack"] = matrix
                state_path = Path(r"D:\PhronesisVault\Operations\logs\lru-router-state.json")
                if state_path.is_file():
                    payload["last_dispatch"] = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            self._send_json(200, payload)
            return
        if path in ("/v1/models", "/models"):
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": REGISTERED_MODELS,
                    "gateway": MOE_GATEWAY_ID,
                    "default_model": "phronesis-sovereign-auto",
                },
            )
            return
        if path.startswith("/v1/models/"):
            model_id = path.split("/v1/models/", 1)[1].strip("/")
            for entry in REGISTERED_MODELS:
                if entry.get("id") == model_id:
                    self._send_json(200, entry)
                    return
            self._send_json(404, {"error": "model_not_found", "id": model_id})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": "not_found"})
            return

        try:
            body = self._read_json()
        except Exception as exc:
            status, err = openai_error(400, f"invalid JSON: {exc}", "invalid_request_error")
            self._send_json(status, err)
            return
        if body.get("__error__"):
            return  # _read_json already sent the response

        model = str(body.get("model") or "phronesis-sovereign-auto")
        messages = body.get("messages") or []
        stream = bool(body.get("stream", False))
        routing = resolve_roleplay_routing(messages, model, body)
        model = str(routing.get("model") or model)

        tools_reserve = _estimate_tools_tokens(body.get("tools")) if body.get("tools") else 0
        try:
            trimmed_messages, trim_meta = trim_messages_tier_aware(
                messages,
                model,
                extra_reserve_tokens=tools_reserve,
            )
            prompt = messages_to_prompt(trimmed_messages)
        except Exception as exc:
            _log_event({"event": "trim_exception", "error": str(exc), "model": model})
            status, err = openai_error(400, f"context trim failed: {exc}", "invalid_request_error")
            self._send_json(status, err)
            return

        if not prompt.strip():
            status, err = openai_error(400, "empty messages", "invalid_request_error")
            self._send_json(status, err)
            return

        if trim_meta.get("trimmed"):
            _log_event(
                {
                    "event": "context_trim",
                    "model": model,
                    "tier": trim_meta.get("tier"),
                    "original_tokens": trim_meta.get("original_tokens_estimate"),
                    "final_tokens": trim_meta.get("final_tokens_estimate"),
                    "dropped_turns": trim_meta.get("dropped_turns"),
                }
            )

        started = time.time()
        use_native = _unified_router_up()
        try:
            if use_native:
                result = dispatch_via_native_router(
                    body,
                    trimmed_messages,
                    model,
                    routing=routing,
                    trim_meta=trim_meta,
                )
            else:
                result = dispatch_via_bridge(
                    prompt, model, trim_meta=trim_meta, routing=routing,
                )
        except Exception as exc:
            _log_event({"event": "dispatch_exception", "error": str(exc), "model": model})
            status, err = openai_error(503, f"dispatch failed: {exc}")
            self._send_json(status, err)
            return

        latency = round(time.time() - started, 2)
        prov = result.get("provenance") or {}

        if result.get("escalation"):
            msg = (
                "[GROK ESCALATION RECOMMENDED] "
                + str(prov.get("escalation_reason") or result.get("response", ""))
            )
            _log_event({"event": "escalation", "model": model, "triggers": prov.get("escalation_triggers")})
            status, err = openai_error(503, msg, "escalation_required")
            self._send_json(status, err)
            return

        if not result.get("success"):
            msg = result.get("response") or "local dispatch failed"
            _log_event({"event": "dispatch_fail", "model": model, "attempts": result.get("attempts")})
            status, err = openai_error(503, msg)
            self._send_json(status, err)
            return

        content = str(result.get("response") or "")
        resolved_model = result.get("model")
        extra = {
            "gateway_model": routing.get("request_model") or model,
            "routing_model": model,
            "routing_platform": routing.get("platform"),
            "routing_reasons": routing.get("reasons"),
            "tier": result.get("tier"),
            "backend": prov.get("selected_backend"),
            "port_hint": prov.get("port_hint"),
            "quality_warning": result.get("quality_warning") or prov.get("quality_warning"),
            "latency_sec": latency,
            "resolved_model": resolved_model,
            "uncensored_route": prov.get("uncensored_route"),
            "context_trim": trim_meta,
            "narrative_fast": bool(routing.get("narrative_fast") or result.get("narrative_fast")),
            "suppress_reasoning": bool(
                routing.get("suppress_reasoning") or result.get("narrative_fast")
            ),
            "native_passthrough": bool(prov.get("native_passthrough")),
            "tool_passthrough": bool(prov.get("tool_passthrough") or result.get("tool_calls")),
        }
        _log_event({"event": "dispatch_ok", "model": model, **{k: v for k, v in extra.items() if k != "context_trim"}})
        _log_generation_provenance({
            "event": "proxy_dispatch_ok",
            "gateway_model": routing.get("request_model") or model,
            "routing_model": model,
            "task_type": routing.get("task_type") or resolve_task_type(model),
            "tier": result.get("tier"),
            "resolved_model": resolved_model,
            "backend": prov.get("selected_backend"),
            "platform": routing.get("platform"),
            "force_roleplay": routing.get("force_roleplay"),
            "response_preview": content[:200],
            "latency_sec": latency,
            "uncensored_route": prov.get("uncensored_route"),
        })

        try:
            is_roleplay = (
                prov.get("uncensored_route")
                or str(result.get("tier") or "") == "local_roleplay"
                or _roleplay_route_requested(model, messages)
            )
            if is_roleplay:
                from roleplay_route_guard import extract_phronesis_body
                from sovereign_memory_manager import checkpoint_roleplay_turn

                ph = extract_phronesis_body(body)
                checkpoint_roleplay_turn(
                    platform=str(routing.get("platform") or "roleplay"),
                    user_content=messages_to_prompt(messages, max_chars=8000),
                    assistant_content=content[:8000],
                    campaign=model,
                    metadata={"gateway_port": DEFAULT_PORT, "latency_sec": latency},
                    chat_id=str(ph.get("chat_id") or routing.get("chat_id") or ""),
                    thread_id=str(ph.get("thread_id") or routing.get("thread_id") or ""),
                    parent_channel_id=str(
                        ph.get("parent_channel_id") or routing.get("parent_channel_id") or ""
                    ),
                )
            else:
                from sovereign_memory_manager import checkpoint_gateway_turn

                checkpoint_gateway_turn(
                    platform="hermes_agent_session",
                    messages=messages,
                    assistant_content=content,
                    procedural_state={
                        "active_task": model,
                        "last_tier": result.get("tier"),
                        "last_model": result.get("model"),
                        "tool_depth": int(body.get("tool_depth") or 0),
                        "pending_delegations": body.get("pending_delegations") or [],
                    },
                    metadata={"gateway_port": DEFAULT_PORT, "latency_sec": latency},
                )
        except Exception:
            pass

        if stream:
            openai_resp = result.get("openai_response") or {}
            choice_msg = ((openai_resp.get("choices") or [{}])[0].get("message") or {})
            stream_tool_calls = result.get("tool_calls") or choice_msg.get("tool_calls")
            stream_finish = result.get("finish_reason") or (
                (openai_resp.get("choices") or [{}])[0].get("finish_reason")
            )
            if stream_tool_calls:
                stream_content = ""
            else:
                stream_content = content
            sse_ok = self._send_sse_chunk(
                model,
                stream_content,
                tool_calls=stream_tool_calls,
                finish_reason=str(stream_finish or "stop"),
            )
            if not sse_ok:
                pass  # Client disconnected; nothing more to do
            return

        report_model = str(resolved_model or model)
        native_resp = result.get("openai_response")
        if isinstance(native_resp, dict):
            out = dict(native_resp)
            out["model"] = report_model
            out["phronesis_provenance"] = extra
            msg = (out.get("choices") or [{}])[0].setdefault("message", {})
            visible = content or _assistant_visible_content(msg, allow_reasoning_fallback=True)
            if visible:
                msg["content"] = visible
            if result.get("narrative_fast") or visible:
                for key in ("reasoning", "reasoning_content", "reasoning_details"):
                    msg.pop(key, None)
            self._send_json(200, out)
            return

        self._send_json(200, openai_chat_response(report_model, content, extra=extra))


def _self_test_trim() -> Dict[str, Any]:
    big = "x" * 12000
    messages = [{"role": "system", "content": "You are Hermes."}]
    for i in range(30):
        messages.append({"role": "user", "content": f"Turn {i}: {big}"})
        messages.append({"role": "assistant", "content": f"Ack {i}"})
    trimmed, meta = trim_messages_tier_aware(messages, "phronesis-sovereign-code")
    prompt = messages_to_prompt(trimmed)

    # Regression: oversized single user turn must not crash on non_system.index()
    skill_blob = "y" * 50_000
    single_turn = [{"role": "user", "content": skill_blob}]
    single_trimmed, single_meta = trim_messages_tier_aware(
        single_turn,
        "phronesis-sovereign-auto",
    )

    return {
        "model": "phronesis-sovereign-code",
        "meta": meta,
        "prompt_chars": len(prompt),
        "prompt_tokens_estimate": estimate_tokens(prompt),
        "under_cap": meta.get("final_tokens_estimate", 0) <= meta.get("input_cap_tokens", 0),
        "single_turn_ok": len(single_trimmed) > 0 and single_meta.get("trimmed") is True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phronesis MoE gateway (OpenAI-compatible protocol)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--test-trim", action="store_true", help="Run tier-aware trim self-test and exit")
    args = parser.parse_args()

    if args.test_trim:
        print(json.dumps(_self_test_trim(), indent=2))
        return 0

    try:
        from ensure_hermes_sovereign_config import ensure_all_configs

        report = ensure_all_configs()
        if report.get("changed"):
            _log_event({"event": "config_ensure", "report": report})
    except Exception as exc:
        print(f"config ensure skipped: {exc}", file=sys.stderr)

    try:
        from sovereign_memory_manager import hydrate_boot_state

        boot = hydrate_boot_state(platform="hermes_agent_session")
        if boot:
            _log_event(
                {
                    "event": "memory_hydrate_boot",
                    "session_id": boot.get("session_id"),
                    "hydrated": boot.get("hydrated"),
                    "turns": len(boot.get("working_memory") or []),
                }
            )
            if boot.get("hydrated"):
                proc = boot.get("procedural_state") or {}
                print(
                    f"Memory hydrated: session={boot.get('session_id')} "
                    f"task={proc.get('active_task')} tier={proc.get('last_tier')}"
                )
    except Exception as exc:
        print(f"memory hydrate skipped: {exc}", file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), SovereignProxyHandler)
    print(f"Phronesis MoE gateway listening on http://{args.host}:{args.port}")
    print("Endpoints: /health /v1/models /v1/chat/completions (tier-aware trim ON)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
