#!/usr/bin/env python3
"""
sovereign_openai_proxy.py -- Phronesis MoE gateway (OpenAI-compatible wire format).

Bridges Hermes primary agent loop -> router_bridge -> local MoE 8081/8082/8083.
Hermes config: custom_providers phronesis-sovereign @ http://127.0.0.1:8091/v1

The /v1/* paths follow the OpenAI Chat Completions *protocol* so Hermes
custom_providers (api_mode: chat_completions) work without cloud OpenAI.
Service identity: phronesis-moe-gateway -- local mixture-of-experts only.

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

# Detach any console so 8091 never flashes / steals focus on launch or heal.
try:
    import ctypes

    if sys.platform == "win32":
        ctypes.windll.kernel32.FreeConsole()
except Exception:
    pass

HERMES_SCRIPTS = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or r"D:\HermesData")
VAULT_SCRIPTS = Path(r"D:\PhronesisVault\scripts")
# tool_call_fixer.py and sibling SSOTs live in HERMES_HOME root - not scripts/.
# Without this, proxy started from System32/schtask cwd silently skips the fixer
# and local 9B [Called tool(...)] leaks reach Discord as final text.
for _p in (HERMES_HOME, HERMES_SCRIPTS, VAULT_SCRIPTS):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

try:
    import proxy_json_repair as _pjr
except Exception:
    _pjr = None  # type: ignore


def _loads_tool_json(text: Any) -> Any:
    """json.loads with proxy_json_repair as a pre-parse fallback.

    Additive: valid JSON is unchanged. Dirty LLM tool payloads (trailing
    commas, missing closers, ```json fences, mixed quotes) are repaired
    instead of becoming empty arguments.
    """
    if isinstance(text, (dict, list)):
        return text
    raw = str(text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty", raw, 0)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    if _pjr is not None:
        try:
            got = _pjr.loads(raw)
            if got is not None:
                return got
        except Exception:
            pass
    return json.loads(raw)

DEFAULT_PORT = 8091
UNIFIED_ROUTER_PORT = 8090
UNIFIED_ROUTER_CHAT = f"http://127.0.0.1:{UNIFIED_ROUTER_PORT}/v1/chat/completions"
# Match config.yaml gateway_timeout (1800s). RP+tools on a single GPU can exceed 5 min.
UPSTREAM_TIMEOUT_SEC = int(os.environ.get("SOVEREIGN_PROXY_UPSTREAM_TIMEOUT", "1800"))
PROXY_LOG = Path(r"D:\PhronesisVault\Operations\logs\sovereign-proxy.jsonl")
GENERATION_PROVENANCE_LOG = Path(r"D:\PhronesisVault\Operations\logs\generation-provenance-trace.jsonl")
# Live activity stamp for /health (unified :8090 path must write; was stale at 2026-07-08).
LRU_ROUTER_STATE = Path(r"D:\PhronesisVault\Operations\logs\lru-router-state.json")

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
    # File / collab -- Qwythos narrates tools unless tool_choice=required
    "read_file",
    "write_file",
    "must use tools",
    "must call tools",
    "grok/cursor",
    "plan-first",
    "grok-hermes",
    "append to",
    "active queue",
    "section 6",
    "collab log",
    "write_file to",
    "phronesisvault",
    # 2026-08-16: 9B invents SAT JSON when these miss house-facts classify
    "speak_and_trust",
    "--status-only",
    "kitchen status",
    "quote receipt",
    "quote the json",
    "autonomy_growth",
    "--orchestrate",
    "vault_search",
    "service_manager",
    "system_telemetry",
)

PRIMER_PATH = HERMES_HOME / "state" / "prompts" / "qwythos_system_primer.md"
_PRIMER_CACHE: Dict[str, Any] = {"mtime": None, "text": ""}
ATOMIC_TOOL_NAMES = ("vault_search", "service_manager", "system_telemetry")
GOLDEN_BANK_PATH = Path(r"D:\PhronesisModels\datasets\sovereign_tool_golden_bank.jsonl")
_GOLDEN_BANK: list = []
_GOLDEN_BANK_MTIME = None

_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)\b[^>]*>.*?</(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)>",
    re.DOTALL | re.IGNORECASE,
)

# Model id suffix -> task_type (config extensible via env JSON path later)
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
# Hermes Agent requires >= 64K advertised context; proxy still trims per-tier before 8090 dispatch.
# SSOT: phronesis-core.json / qwythos_8090_profile.json ctx_size (raised 64k->128k 2026-08-03)
DEFAULT_CONTEXT_LENGTH = 131072
MOE_GATEWAY_ID = "phronesis-moe-gateway"
MOE_OWNER = "phronesis-moe"

MODEL_SPECS: List[Dict[str, Any]] = [
    {"id": "phronesis-sovereign-auto", "name": "Phronesis MoE Auto", "tier": "auto", "task_type": None},
    # Explicit Qwythos alias (same unified 8090 backbone as auto)
    {"id": "qwythos-9b", "name": "Qwythos 9B Local Backbone", "tier": "auto", "task_type": None},
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

from proxy_trim import (  # noqa: E402
    extract_message_content as _extract_content,
    estimate_tokens,
    message_tokens as _message_tokens,
    estimate_tools_tokens as _estimate_tools_tokens,
    truncate_text as _truncate_text,
    truncate_message as _truncate_message,
    truncate_messages as _truncate_messages,
    compress_history_stub as _compress_history_stub,
    trim_messages_tier_aware,
    messages_to_prompt,
    fifo_pressure_reserve_tokens as _fifo_pressure_reserve_tokens,
    estimate_context_tokens,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
_LOG_BACKUP_COUNT = 3

# ----------------------------------------------------------------------
# Batch 5 (2026-06-29): Connection pool, prompt cache, circuit breaker
# Research: iunera.com middleware pattern, Vercel AI SDK connection reuse,
#           Gravitee semantic caching, circuit breaker standard pattern.
# ----------------------------------------------------------------------

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
        conn = HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT_SEC)
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


_upstream_pool = _ConnectionPool(max_per_host=4, keep_alive_sec=60)


class _PromptCache:
    """Tiny LRU cache for identical prompt -> response (stdinference save for repeated tool schemas)."""

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
    """Prevent hammering a down upstream -- half-open after cooldown."""

    def __init__(self, failure_threshold: int = 5, cooldown_sec: float = 30.0):
        self._failures = 0
        self._threshold = failure_threshold
        self._cooldown = cooldown_sec
        self._opened_at: float = 0.0
        self._lock = threading.Lock()
        self._state = "closed"  # closed | open | half-open
        self._force_open = False  # W2-P1 lab: admin force-open (skips cooldown)

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._force_open = False
            self._state = "closed"

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = "open"
                self._opened_at = time.time()

    def force_open(self) -> None:
        """Lab/admin: pin circuit OPEN until force_close or success."""
        with self._lock:
            self._force_open = True
            self._state = "open"
            self._opened_at = time.time()
            self._failures = max(self._failures, self._threshold)

    def force_close(self) -> None:
        """Lab/admin: clear force-open and reset breaker."""
        with self._lock:
            self._force_open = False
            self._failures = 0
            self._state = "closed"
            self._opened_at = 0.0

    @property
    def allow_request(self) -> bool:
        with self._lock:
            if self._force_open:
                return False
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
        with self._lock:
            if self._force_open:
                return "open"
            return self._state

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": "open" if self._force_open else self._state,
                "failures": self._failures,
                "force_open": self._force_open,
                "opened_at": self._opened_at,
                "threshold": self._threshold,
                "cooldown_sec": self._cooldown,
            }


# Per-upstream circuit breakers keyed by port
_breakers: Dict[int, _CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def _get_breaker(port: int) -> _CircuitBreaker:
    with _breakers_lock:
        if port not in _breakers:
            _breakers[port] = _CircuitBreaker(failure_threshold=5, cooldown_sec=30)
        return _breakers[port]


def _resolve_queue_caller(
    handler: "SovereignProxyHandler",
    routing: Dict[str, Any],
    body: Dict[str, Any],
) -> str:
    header = (handler.headers.get("X-Phronesis-Caller") or "").strip()
    if header:
        return header[:120]
    platform = str(routing.get("platform") or "").strip()
    chat_id = str(routing.get("chat_id") or routing.get("thread_id") or "").strip()
    if platform and chat_id:
        return f"{platform}:{chat_id}"[:120]
    if platform:
        return platform[:120]
    try:
        from roleplay_route_guard import extract_phronesis_body

        ph = extract_phronesis_body(body)
        if ph.get("platform"):
            return str(ph.get("platform"))[:120]
    except Exception:
        pass
    return "hermes"


def _queue_ticket_dict(ticket: Any) -> Dict[str, Any]:
    return {
        "id": ticket.id,
        "lane": "roleplay" if ticket.lane == 0 else "normal",
        "position": ticket.position,
        "wait_sec": ticket.wait_sec,
        "eta_sec": ticket.eta_sec,
    }


def _dispatch_upstream_with_pool(url: str, payload: bytes,
                                content_type: str = "application/json",
                                max_attempts: int = 2) -> Dict[str, Any]:
    """Serialize an upstream call through the circuit breaker + connection pool."""
    from urllib.parse import urlparse as _up
    parsed = _up(url)
    port = parsed.port or 80
    breaker = _get_breaker(port)
    if not breaker.allow_request:
        raise ConnectionError(f"Circuit breaker OPEN for port {port} - upstream appears down")
    headers = {"Content-Type": content_type}
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, max_attempts)):
        try:
            status, data = _upstream_pool.request("POST", url, body=payload, headers=headers)
            breaker.record_success()
            return {"status": status, "body": data}
        except Exception as exc:
            last_exc = exc
            breaker.record_failure()
            msg = str(exc).lower()
            transient = any(
                token in msg
                for token in (
                    "10053",
                    "10054",
                    "connection was aborted",
                    "connection was closed",
                    "broken pipe",
                    "reset by peer",
                    "timed out",
                )
            )
            if not transient or attempt >= max_attempts - 1:
                raise
            time.sleep(0.35 * (attempt + 1))
    if last_exc:
        raise last_exc
    raise ConnectionError("upstream dispatch failed")


# ----------------------------------------------------------------------
# Batch 5 END
# ----------------------------------------------------------------------


def _rotate_if_needed(path: Path) -> None:
    """Rotate path -> path.1 .. path.N when over max bytes.

    Uses ``str(path) + '.N'`` backups (not Path.with_suffix) so ``.jsonl``
    names stay intact. Previous bug: ``path.withsuffix`` (typo) + bad
    with_suffix args raised AttributeError; bare ``except`` swallowed it and
    **silently stopped all provenance/proxy logging** once files exceeded 10MB
    (observed 2026-07-18: last provenance event 2026-07-13).
    """
    try:
        if not path.exists() or path.stat().st_size <= _LOG_MAX_BYTES:
            return
        # Shift path.N-1 -> path.N
        for i in range(_LOG_BACKUP_COUNT - 1, 0, -1):
            older = Path(f"{path}.{i + 1}")
            newer = Path(f"{path}.{i}")
            if older.exists():
                older.unlink()
            if newer.exists():
                newer.rename(older)
        first = Path(f"{path}.1")
        if first.exists():
            first.unlink()
        path.rename(first)
    except Exception:
        # Never block inference on log I/O -- but do not mask forever:
        # size stuck above max would skip writes if rotate keeps failing.
        # Caller still tries append; if rename failed, append may still work.
        pass


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


def _touch_last_dispatch(
    *,
    logical_model: str = "",
    task_type: str = "",
    tier: str = "",
    backend: str = "",
) -> None:
    """Update lru-router-state.json so /health last_dispatch reflects real traffic.

    Pre-unified LRU path wrote this file; native :8090 dispatch did not, so panels
    showed last_dispatch frozen at 2026-07-08 while provenance was live (audit 2026-07-18).
    Never block inference on stamp I/O.
    """
    try:
        state: Dict[str, Any] = {}
        if LRU_ROUTER_STATE.is_file():
            try:
                loaded = json.loads(LRU_ROUTER_STATE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state = loaded
            except Exception:
                state = {}
        now = _utc_now()
        state["last_dispatch"] = now
        if logical_model:
            state["last_logical_model"] = logical_model
            preload = state.get("last_preload")
            if not isinstance(preload, dict):
                preload = {}
            preload[str(logical_model)] = now
            state["last_preload"] = preload
        if task_type:
            state["last_task_type"] = task_type
        if tier:
            state["last_tier"] = tier
        if backend:
            state["last_backend"] = backend
        state["session_active"] = True
        state["updated_by"] = "sovereign_openai_proxy"
        LRU_ROUTER_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LRU_ROUTER_STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(LRU_ROUTER_STATE)
    except Exception:
        pass


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


def _flatten_tool_history_for_llama(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert cloud/Grok OpenAI tool-call history into plain text for llama-server.

    Grok-era sessions keep assistant ``tool_calls`` + ``tool`` role turns in history.
    llama-server's chat template often fails with HTTP 400 "Unable to generate parser
    for this template" when those shapes are present - even after the request ``tools``
    array is stripped.  Idempotent: already-flat messages pass through with junk keys removed.
    """
    out: List[Dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        if role == "tool":
            name = str(msg.get("name") or msg.get("tool_call_id") or "tool")
            content = _extract_content(msg.get("content"))
            preview = content[:2400] + ("..." if len(content) > 2400 else "")
            if preview.strip():
                out.append({"role": "user", "content": f"[Tool result - {name}]: {preview}"})
            continue
        if role == "assistant" and msg.get("tool_calls"):
            parts: List[str] = []
            visible = _assistant_visible_content(msg, allow_reasoning_fallback=False)
            if visible:
                parts.append(visible)
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = str((fn or {}).get("name") or "tool")
                args = str((fn or {}).get("arguments") or "")[:800]
                parts.append(f"[Called {name}({args})]")
            out.append({"role": "assistant", "content": "\n".join(parts) if parts else "[assistant tool turn]"})
            continue
        content = _extract_content(msg.get("content"))
        if role == "assistant" and not content:
            content = _assistant_visible_content(msg)
        if role == "system" or content.strip():
            clean = {"role": role, "content": content}
            if msg.get("name"):
                clean["name"] = msg["name"]
            out.append(clean)
    return out if out else list(messages or [])


def resolve_task_type(model: str) -> Optional[str]:
    model_l = (model or "").lower()
    for suffix, task_type in MODEL_TASK_MAP.items():
        if model_l.endswith(f"-{suffix}") or model_l == f"phronesis-sovereign-{suffix}":
            return task_type
    if "sovereign" in model_l:
        return None
    return None


_FAST_ROUTE_BY_TASK: Dict[Optional[str], Dict[str, Any]] = {
    "roleplay": {"task_type": "roleplay", "tier": "local_roleplay", "port": UNIFIED_ROUTER_PORT},
    "code": {"task_type": "code", "tier": "local_hot", "port": UNIFIED_ROUTER_PORT},
    "simple": {"task_type": "simple", "tier": "local_hot", "port": UNIFIED_ROUTER_PORT},
    "classify": {"task_type": "classify", "tier": "local_hot", "port": UNIFIED_ROUTER_PORT},
    "metadata_extraction": {"task_type": "metadata_extraction", "tier": "local_hot", "port": UNIFIED_ROUTER_PORT},
    "synthesis": {"task_type": "synthesis", "tier": "local_warm", "port": UNIFIED_ROUTER_PORT},
    "deep_analysis": {"task_type": "deep_analysis", "tier": "local_cold", "port": UNIFIED_ROUTER_PORT},
}


def _single_model_unified_lock() -> bool:
    try:
        core_path = HERMES_SCRIPTS / "phronesis-core.json"
        if core_path.is_file():
            core = json.loads(core_path.read_text(encoding="utf-8"))
            return bool(core.get("model_rotation_locked") or core.get("model_locked"))
    except Exception:
        pass
    return True


def preview_route_for_request(model: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    task_type = resolve_task_type(model)
    if task_type in _FAST_ROUTE_BY_TASK and _unified_router_up():
        route = {
            **_FAST_ROUTE_BY_TASK[task_type],
            "unified_router": True,
            "inferred": False,
            "fast_path": True,
        }
    else:
        from router_bridge import preview_route

        infer_prompt = messages_to_prompt(messages, max_chars=4000)
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
    if route.get("unified_router") and not _single_model_unified_lock():
        try:
            from lru_router_manager import preload_from_route_preview
            route["preload"] = preload_from_route_preview(route)
        except Exception as exc:
            route["preload"] = {"ok": False, "error": str(exc)}
    elif route.get("unified_router"):
        route["preload"] = {"ok": True, "skipped": True, "reason": "single_model_lock"}
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


def prepare_prompt_for_dispatch(
    messages: List[Dict[str, Any]],
    model: str,
) -> Tuple[str, Dict[str, Any]]:
    trimmed_messages, trim_meta = trim_messages_tier_aware(messages, model)
    prompt = messages_to_prompt(trimmed_messages)
    return prompt, trim_meta


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


def _user_developer_blob(messages: List[Dict[str, Any]]) -> str:
    """User/developer text only -- system prompts mention #alice-roleplay as policy."""
    parts: List[str] = []
    for msg in messages or []:
        if str(msg.get("role") or "").lower() in ("user", "developer"):
            parts.append(_extract_content(msg.get("content")))
    return "\n".join(parts)


def _roleplay_route_active(
    routing: Optional[Dict[str, Any]] = None,
    model: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """True when this turn must use narrative-fast (no llama tool grammar)."""
    routing = routing or {}
    model_l = (model or routing.get("model") or "").lower()
    if routing.get("force_roleplay"):
        return True
    if routing.get("task_type") == "roleplay":
        return True
    if "roleplay" in model_l:
        return True
    blob = _user_developer_blob(messages or []).lower()
    if any(
        token in blob
        for token in (
            "#alice-roleplay",
            "alice rp sandbox",
            "alice narrator thread",
            "platform alice-roleplay",
        )
    ):
        return True
    return False


def _blob_has_factual_tool_intent(blob: str) -> bool:
    """Match factual tool intent without false positives from image_generate policy text."""
    lower = (blob or "").lower()
    for marker in FACTUAL_TOOL_MARKERS:
        if marker == "image_gen":
            if re.search(r"\bimage_gen\b", lower):
                return True
            continue
        if marker in lower:
            return True
    return False


def is_narrative_fast_path(
    messages: List[Dict[str, Any]],
    body: Optional[Dict[str, Any]] = None,
    routing: Optional[Dict[str, Any]] = None,
) -> bool:
    """Detect creative/narrative turns that must skip reasoning traces."""
    body = body or {}
    routing = routing or {}
    model = str(routing.get("model") or body.get("model") or "")
    if _roleplay_route_active(routing, model, messages):
        return True
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
    blob = _message_blob(messages).lower()
    if _blob_has_factual_tool_intent(blob):
        return False
    if not any(marker in blob for marker in NARRATIVE_FAST_MARKERS):
        return False
    return "alice-roleplay" in blob or "#alice-roleplay" in blob


def _requires_factual_tool_use(
    messages: List[Dict[str, Any]],
    routing: Optional[Dict[str, Any]] = None,
    model: str = "",
) -> bool:
    if _roleplay_route_active(routing, model, messages):
        return False
    last_user = ""
    for msg in reversed(messages or []):
        if isinstance(msg, dict) and str(msg.get("role") or "").lower() == "user":
            last_user = _extract_content(msg.get("content")).lower()
            break
    return _blob_has_factual_tool_intent(last_user)


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


def _build_read_file_tool_call(path: str) -> Dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": json.dumps({"path": path}),
        },
    }


def _build_write_file_tool_call(path: str, content: str = "") -> Dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": path, "content": content}),
        },
    }


def _synthesize_file_tool_call(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Derive read_file/write_file from explicit paths in user instructions."""
    for msg in reversed(messages or []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = _extract_content(msg.get("content"))
        lower = content.lower()
        if "write_file" in lower:
            m = re.search(
                r"write_file\s+(?:to\s+)?([A-Za-z]:\\[^\s`\"']+\.md)",
                content,
                re.IGNORECASE,
            )
            if m:
                return _build_write_file_tool_call(m.group(1).strip())
        if "read_file" in lower:
            m = re.search(
                r"read_file\s+(?:on\s+)?([A-Za-z]:\\[^\s`\"']+\.md)",
                content,
                re.IGNORECASE,
            )
            if m:
                return _build_read_file_tool_call(m.group(1).strip())
            paths = re.findall(r"(D:\\[^\s`\"']+\.md)", content, re.IGNORECASE)
            if paths:
                return _build_read_file_tool_call(paths[0])
        break
    return None


def _build_image_generate_tool_call(prompt: str, aspect_ratio: str = "portrait") -> Dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": "image_generate",
            "arguments": json.dumps({"prompt": prompt, "aspect_ratio": aspect_ratio}),
        },
    }


def _count_recent_tool_failures(messages: List[Dict[str, Any]], *, window: int = 12) -> int:
    """Count recent tool results that look like failures (for T2 escalation)."""
    fails = 0
    for msg in (messages or [])[-window:]:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        blob = str(msg.get("content") or "").lower()
        if any(
            sig in blob
            for sig in (
                '"success": false',
                '"success":false',
                "error",
                "failed",
                "provider_not_registered",
                "tool error",
            )
        ):
            fails += 1
    return fails


def _synthesize_image_generate_call(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Derive image_generate from OOC portrait/scene/picture-mode user triggers."""
    for msg in reversed(messages or []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = _extract_content(msg.get("content"))
        lower = content.lower()
        if not any(
            k in lower
            for k in (
                "ooc:",
                "picture mode",
                "portrait ",
                "scene:",
                "generate image",
                "image_generate",
            )
        ):
            break
        prompt = content
        if "ooc:" in lower:
            prompt = re.sub(r"(?i)^\s*ooc:\s*", "", content).strip()
        if not prompt:
            break
        aspect = "portrait" if "portrait" in lower or "picture" in lower else "landscape"
        return _build_image_generate_tool_call(prompt, aspect_ratio=aspect)
    return None


def _inject_tool_optimised_mode(
    messages: List[Dict[str, Any]],
    *,
    tier: str = "T1",
) -> List[Dict[str, Any]]:
    note = (
        f"You are now in tool-optimised mode ({tier}). "
        "Do NOT describe tool use in prose. Do NOT write [Called ...]. "
        "Prefer vault_search, service_manager, or system_telemetry over raw PowerShell. "
        'Emit ONLY a raw tool call: <tool_call>{"name":"system_telemetry","arguments":{}}</tool_call> then stop.'
    )
    out = list(messages or [])
    out.insert(0, {"role": "system", "content": note})
    return out


def _load_qwythos_primer() -> str:
    path = PRIMER_PATH
    try:
        import yaml  # type: ignore

        cfg = yaml.safe_load(Path(r"D:\HermesData\config.yaml").read_text(encoding="utf-8")) or {}
        cfg_path = str(((cfg.get("local_sovereign") or {}).get("system_primer") or "")).strip()
        if cfg_path:
            path = Path(cfg_path)
    except Exception:
        pass
    try:
        st = path.stat()
    except OSError:
        return str(_PRIMER_CACHE.get("text") or "")
    if _PRIMER_CACHE.get("mtime") == st.st_mtime and _PRIMER_CACHE.get("text"):
        return str(_PRIMER_CACHE["text"])
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    _PRIMER_CACHE["mtime"] = st.st_mtime
    _PRIMER_CACHE["text"] = text
    return text


def _load_golden_bank() -> list:
    global _GOLDEN_BANK, _GOLDEN_BANK_MTIME
    try:
        st = GOLDEN_BANK_PATH.stat()
    except OSError:
        return _GOLDEN_BANK
    if _GOLDEN_BANK_MTIME == st.st_mtime and _GOLDEN_BANK:
        return _GOLDEN_BANK
    rows = []
    with GOLDEN_BANK_PATH.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    _GOLDEN_BANK = rows
    _GOLDEN_BANK_MTIME = st.st_mtime
    return rows


def _inject_entity_context(
    messages: List[Dict[str, Any]],
    routing: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    routing = routing or {}
    try:
        import entity_pre_inject as epi
    except Exception:
        return list(messages or []), {}
    try:
        out, meta = epi.inject_messages(messages, routing)
        return out, meta or {}
    except Exception as exc:
        try:
            _log_event({"event": "entity_pre_inject_fail", "error": str(exc)[:160]})
        except Exception:
            pass
        return list(messages or []), {}


def _inject_golden_fewshot(
    messages: List[Dict[str, Any]],
    routing: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    routing = routing or {}
    if routing.get("narrative_fast") or routing.get("roleplay") or routing.get("is_roleplay"):
        return messages
    blob = " ".join(
        str(m.get("content") or "")[:400]
        for m in (messages or [])
        if isinstance(m, dict) and m.get("role") == "user"
    ).lower()
    if not blob:
        return messages
    bank = _load_golden_bank()
    if not bank:
        return messages
    scored = []
    for rec in bank:
        u = str(rec.get("user") or "").lower()
        hits = sum(1 for w in u.split() if len(w) > 3 and w in blob)
        if hits:
            scored.append((hits, rec))
    scored.sort(key=lambda x: -x[0])
    picks = [r for _, r in scored[:3]]
    if not picks:
        return messages
    lines = ["GOLDEN TOOL EXAMPLES (copy the <tool_call> shape; never narrate):"]
    for rec in picks:
        lines.append("User: " + str(rec.get("user") or "")[:160])
        block = rec.get("tool_call") or rec.get("assistant") or rec.get("refusal") or ""
        lines.append(str(block)[:400])
        lines.append("")
    note = "\n".join(lines)[:1400]
    out = list(messages or [])
    out.insert(0, {"role": "system", "content": note})
    return out


def _inject_qwythos_primer(
    messages: List[Dict[str, Any]],
    routing: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    routing = routing or {}
    if routing.get("narrative_fast") or routing.get("roleplay") or routing.get("is_roleplay"):
        return messages
    text = _load_qwythos_primer()
    if not text:
        return messages
    for msg in (messages or [])[:4]:
        if isinstance(msg, dict) and "QWYTHOS 9B SYSTEM PRIMER" in str(msg.get("content") or ""):
            return messages
    out = list(messages or [])
    out.insert(0, {"role": "system", "content": text})
    return out


def _atomic_catalogue():
    try:
        tools_dir = str(HERMES_SCRIPTS / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import atomic_tool_catalogue as cat  # type: ignore

        return cat
    except Exception:
        return None


def _tool_schema_names(tools: Optional[List[Any]]) -> set:
    names: set = set()
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        n = fn.get("name") if isinstance(fn, dict) else None
        if n:
            names.add(str(n))
    return names


def _merge_atomic_tools(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    cat = _atomic_catalogue()
    if cat is None:
        return list(tools or [])
    try:
        return cat.merge_atomic_schemas(tools)
    except Exception:
        return list(tools or [])


def _rewrite_atomic_tool_calls(
    tool_calls: Optional[List[Dict[str, Any]]],
    gateway_names: Optional[set] = None,
) -> Optional[List[Dict[str, Any]]]:
    cat = _atomic_catalogue()
    if cat is None or not tool_calls:
        return tool_calls
    try:
        return cat.rewrite_tool_calls(tool_calls, set(gateway_names or ()))
    except Exception:
        return tool_calls


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

_FENCE_JSON_RE = re.compile(
    r"```(?:json|tool|javascript)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

_COLLAB_BLOCKED_TOOLS = frozenset({"web_extract", "web_search", "image_generate"})


def _unwrap_markdown_json_fence(text: str) -> str:
    """Strip ```json fences so narrated tool blobs can be coerced."""
    raw = (text or "").strip()
    if not raw:
        return raw
    match = _FENCE_JSON_RE.search(raw)
    if match:
        return match.group(1).strip()
    if raw.startswith("```") and raw.endswith("```"):
        inner = raw.strip("`").strip()
        if inner.lower().startswith("json"):
            inner = inner[4:].strip()
        return inner
    return raw


def _coerce_write_file_from_narration(text: str) -> tuple[str, dict] | None:
    """Fallback when Qwythos emits write_file JSON with invalid Windows path escapes."""
    raw = (text or "").strip()
    if "write_file" not in raw:
        return None
    path_m = re.search(r'"path"\s*:\s*"(D:[^"\n]+)"', raw, re.IGNORECASE)
    if not path_m:
        return None
    mode_m = re.search(r'"mode"\s*:\s*"(\w+)"', raw, re.IGNORECASE)
    content_m = re.search(
        r'"content"\s*:\s*"(.*?)"\s*\n?\s*\}',
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    body = ""
    if content_m:
        body = content_m.group(1).replace("\\n", "\n").replace('\\"', '"')
    return "write_file", {
        "path": path_m.group(1).replace("\\\\", "\\"),
        "mode": (mode_m.group(1) if mode_m else "append"),
        "content": body,
    }


def _extract_tool_from_payload(payload: dict) -> tuple[str | None, dict]:
    """Normalize Qwythos narrated tool dicts to (name, args)."""
    if not isinstance(payload, dict):
        return None, {}
    name = payload.get("name") or payload.get("tool")
    if not name and payload.get("path") and payload.get("content"):
        name = "write_file"
    args = payload.get("arguments") or payload.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = _loads_tool_json(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    for key in ("path", "content", "mode", "offset", "limit"):
        if key in payload and key not in args:
            args[key] = payload[key]
    return (str(name) if name else None), args


def _normalize_llamacpp_tool_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce llama.cpp XML/JSON tool blobs into OpenAI tool_calls array."""
    msg = dict(message or {})
    if msg.get("tool_calls"):
        return msg
    content = _unwrap_markdown_json_fence(str(msg.get("content") or ""))
    extracted: List[Dict[str, Any]] = []
    for pattern in _TOOL_XML_PATTERNS:
        for match in pattern.finditer(content):
            try:
                payload = _loads_tool_json(match.group(1))
            except Exception:
                continue
            name = payload.get("name") or payload.get("tool")
            args = payload.get("arguments") or payload.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = _loads_tool_json(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            if not args.get("path") and payload.get("path"):
                args = {**args, "path": payload["path"]}
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
    if not extracted and content.strip().startswith("{"):
        try:
            payload = _loads_tool_json(content.strip())
            name, args = _extract_tool_from_payload(payload)
            if name and name not in _COLLAB_BLOCKED_TOOLS:
                extracted.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args),
                        },
                    }
                )
        except Exception:
            pass
    if not extracted:
        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = _loads_tool_json(line)
            except Exception:
                continue
            name, args = _extract_tool_from_payload(payload)
            if not name or name in _COLLAB_BLOCKED_TOOLS:
                continue
            extracted.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args),
                    },
                }
            )
    if not extracted:
        wf = _coerce_write_file_from_narration(content)
        if wf:
            name, args = wf
            extracted.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args),
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
    llama_port = UNIFIED_ROUTER_PORT
    try:
        import yaml  # type: ignore
        from pathlib import Path as _P

        _ls = (yaml.safe_load(_P(r"D:\HermesData\config.yaml").read_text(encoding="utf-8")) or {}).get("local_sovereign") or {}
        if _ls.get("deep_reasoning_mode") and str(routing.get("task_type") or "") in {
            "deep_analysis",
            "synthesis",
            "code",
        }:
            _p = int(((_ls.get("deep_reasoner") or {}).get("port") or 8092))
            s = socket.socket()
            s.settimeout(0.4)
            try:
                if s.connect_ex(("127.0.0.1", _p)) == 0:
                    llama_port = _p
                    routing["deep_reasoner"] = True
            finally:
                s.close()
    except Exception:
        llama_port = UNIFIED_ROUTER_PORT
    logical = resolve_backend_logical_model(gateway_model, routing)
    gateway_model = str(routing.get("model") or gateway_model or "")
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
    factual_tools = _requires_factual_tool_use(messages, routing=routing, model=gateway_model)
    requested_max = int(body.get("max_tokens") or 2048)
    safe_max = max(512, live_ctx - prompt_tokens - tools_tokens - 256)
    # Deep synthesis / factual tools: 2048. Conversational RP stays on nf_cap.
    cap = 4096 if (tool_passthrough or factual_tools) else 2048
    max_tokens = min(requested_max, safe_max, cap)
    if tool_passthrough or factual_tools:
        max_tokens = max(max_tokens, min(2048, safe_max))
    elif not narrative_fast:
        max_tokens = max(max_tokens, min(2048, safe_max, cap))

    # Proactive: flatten cloud/Grok tool-call history before first llama-server hit.
    # Prevents HTTP 400 "Unable to generate parser for this template / CallExpression"
    # storms that used to surface as retriable 503s.
    history_has_tools = any(
        isinstance(m, dict)
        and (m.get("role") == "tool" or (m.get("role") == "assistant" and m.get("tool_calls")))
        for m in (messages or [])
    )
    prep_messages = messages
    history_flattened = False
    if history_has_tools:
        prep_messages = _flatten_tool_history_for_llama(messages)
        history_flattened = True
        try:
            prep_messages, _ = trim_messages_tier_aware(
                prep_messages,
                gateway_model or "phronesis-sovereign-auto",
            )
        except Exception:
            pass
        _log_event({
            "event": "proactive_tool_history_flatten",
            "model": logical,
            "orig_turns": len(messages or []),
            "flat_turns": len(prep_messages or []),
        })

    forward: Dict[str, Any] = {
        "model": logical,
        "messages": prep_messages,
        "max_tokens": max_tokens,
        "temperature": body.get("temperature", 0.7),
        "stream": False,
    }
    # Tool schema: allow passthrough for RP stills even when narrative_fast
    # (enable_thinking off already). Factual required tools still prefer non-fast.
    if tool_passthrough or factual_tools:
        if body.get("tools") and (not narrative_fast or tool_passthrough):
            forward["tools"] = body["tools"] if narrative_fast else _merge_atomic_tools(body.get("tools"))
        if factual_tools and body.get("tools") and not narrative_fast:
            if not routing.get("entity_skip_vault"):
                forward["tool_choice"] = "required"
        elif body.get("tool_choice") is not None and (not narrative_fast or tool_passthrough):
            forward["tool_choice"] = body["tool_choice"]

    # Thinking models (Qwythos/Qwen3) consume max_tokens in reasoning_content unless disabled.
    forward["chat_template_kwargs"] = {"enable_thinking": False}

    if narrative_fast:
        # 2026-08-10 Just Alice: hard 384 caused finish_reason=length mid-ERP beat
        # ("Response remained truncated after continuation attempts"). Prefer
        # complete short IC beats over silent mid-clause cuts. Voice/micro can
        # still pass a low max_tokens in the request body.
        requested_nf = int(forward.get("max_tokens") or 2048)
        # Pure IC heat needs ~1–3 finished beats (~800–1500 tok), not essay walls.
        # 1024 was clipping mid-clause; 1536 keeps latency tight vs 2048 synthesis.
        nf_cap = 1536
        if requested_nf <= 256:
            # Explicit micro/voice budget — honor it
            nf_cap = max(128, requested_nf)
        forward["max_tokens"] = min(requested_nf, nf_cap, max(512, safe_max))
        forward["temperature"] = min(float(forward.get("temperature") or 0.85), 0.9)
        # Keep tools when gateway asked for still/tool turn; only strip on pure IC.
        if not tool_passthrough:
            forward.pop("tools", None)
            forward.pop("tool_choice", None)
        elif body.get("tools") and "tools" not in forward:
            # RP + stills: narrative_fast used to drop tools always; restore when requested
            forward["tools"] = body["tools"]
            if body.get("tool_choice") is not None:
                forward["tool_choice"] = body["tool_choice"]

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
                # Skip upstream call -- go straight to response parsing
                choice = (data.get("choices") or [{}])[0]
                raw_msg = choice.get("message") or {}
                content = _assistant_visible_content(raw_msg, allow_reasoning_fallback=True)
                prov = {
                    "selected_backend": "native_8090_cached",
                    "logical_model": logical,
                    "native_passthrough": True,
                    "cached": True,
                    "history_flattened": history_flattened,
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

        def _dispatch_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
            raw = json.dumps(payload).encode("utf-8")
            chat_url = f"http://127.0.0.1:{llama_port}/v1/chat/completions"
            return _dispatch_upstream_with_pool(chat_url, raw)

        result = _dispatch_payload(forward)
        if result["status"] != 200:
            err_body = result.get("body") or b""
            err_text = err_body.decode("utf-8", errors="replace") if isinstance(err_body, (bytes, bytearray)) else str(err_body)
            grammar_fail = (
                result["status"] == 400
                and (
                    "unable to generate parser" in err_text.lower()
                    or "callexpression" in err_text.lower()
                    or "template" in err_text.lower()
                )
            )
            if grammar_fail:
                retry_candidates: List[Dict[str, Any]] = []
                if forward.get("tools"):
                    no_tools = dict(forward)
                    no_tools.pop("tools", None)
                    no_tools.pop("tool_choice", None)
                    retry_candidates.append(no_tools)
                # Always offer a flat-history + no-tools candidate (even if already flattened).
                flat_msgs = _flatten_tool_history_for_llama(forward.get("messages") or [])
                try:
                    flat_msgs, _ = trim_messages_tier_aware(
                        flat_msgs,
                        gateway_model or "phronesis-sovereign-auto",
                    )
                except Exception:
                    pass
                flat_forward = {
                    **forward,
                    "messages": flat_msgs,
                    "max_tokens": min(int(forward.get("max_tokens") or 512), 384),
                    "temperature": min(float(forward.get("temperature") or 0.7), 0.85),
                }
                flat_forward.pop("tools", None)
                flat_forward.pop("tool_choice", None)
                retry_candidates.append(flat_forward)
                # Nuclear: keep system + last 4 plain turns only (no tools). Recovers
                # long tool-heavy Hermes sessions that still break jinja after flatten.
                sys_msgs = [
                    m
                    for m in (flat_msgs or [])
                    if isinstance(m, dict) and str(m.get("role") or "") == "system"
                ][:1]
                if sys_msgs and isinstance(sys_msgs[0].get("content"), str):
                    sc = sys_msgs[0]["content"]
                    if len(sc) > 6000:
                        sys_msgs = [
                            {
                                **sys_msgs[0],
                                "content": sc[:6000]
                                + "\n...[system truncated for llama template recovery]",
                            }
                        ]
                tail = [
                    m
                    for m in (flat_msgs or [])
                    if isinstance(m, dict) and str(m.get("role") or "") != "system"
                ][-4:]
                if not tail:
                    tail = [
                        {
                            "role": "user",
                            "content": (
                                "Continue the conversation briefly. "
                                "(local template recovery path)"
                            ),
                        }
                    ]
                nuclear_msgs = sys_msgs + tail
                nuclear_forward = {
                    "model": forward.get("model") or logical,
                    "messages": nuclear_msgs,
                    "max_tokens": min(int(forward.get("max_tokens") or 384), 384),
                    "temperature": min(float(forward.get("temperature") or 0.7), 0.85),
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                retry_candidates.append(nuclear_forward)
                recovered = False
                for idx, retry_forward in enumerate(retry_candidates):
                    if idx == 0 and forward.get("tools"):
                        event = "grammar_retry_no_tools"
                    elif idx == len(retry_candidates) - 1:
                        event = "grammar_retry_nuclear_short"
                    else:
                        event = "grammar_retry_flat_history"
                    _log_event({"event": event, "model": logical, "attempt": idx + 1})
                    result = _dispatch_payload(retry_forward)
                    if result["status"] == 200:
                        forward = retry_forward
                        narrative_fast = True
                        recovered = True
                        break
                if not recovered:
                    rb = result.get("body") or b""
                    err_tail = rb.decode("utf-8", errors="replace") if isinstance(rb, (bytes, bytearray)) else str(rb)
                    # Permanent template failure ? surface as 400 upstream HTTP so
                    # the proxy maps to invalid_request_error (not retriable 503).
                    raise RuntimeError(
                        f"upstream returned HTTP 400: template/grammar permanent fail: {err_tail[:200]!r}"
                    )
            else:
                raise RuntimeError(f"upstream returned HTTP {result['status']}: {err_text[:200]}")
        data = json.loads(result["body"].decode("utf-8"))

        # Cache the response
        if use_cache and data:
            _prompt_cache.put(logical, cache_key_for_body, result["body"].decode("utf-8"))
    except Exception as exc:
        err_s = str(exc)
        try:
            from sovereign_failure_taxonomy import classify_dispatch_failure

            fail_meta = classify_dispatch_failure(err_s)
        except Exception:
            fail_meta = {
                "failure_class": "unknown",
                "http_status": 503,
                "error_type": "server_error",
                "retryable": True,
            }
        return {
            "success": False,
            "response": f"[NATIVE ROUTER] dispatch failed: {exc}",
            "model": logical,
            "tier": "local_generalist",
            "provenance": {
                "selected_backend": "native_8090",
                "error": err_s,
                "history_flattened": history_flattened,
                **fail_meta,
            },
            "latency_sec": round(time.time() - started, 2),
            "failure_class": fail_meta.get("failure_class"),
            "client_http_status": fail_meta.get("http_status"),
        }

    choice = (data.get("choices") or [{}])[0]
    raw_msg = choice.get("message") or {}
    msg = _normalize_llamacpp_tool_message(raw_msg)
    # Chain ToolCallFixer for abliterated model repair (markdown-fenced JSON, multi-tool blocks)
    # Critical for local Qwythos: after grammar_retry_no_tools the model often emits
    # narrated [Called web_search(...)] as plain text - convert to real tool_calls.
    try:
        from tool_call_fixer import ToolCallFixer

        _tc_fixer = getattr(dispatch_via_native_router, "_tc_fixer", None)
        if _tc_fixer is None:
            _tc_fixer = ToolCallFixer()
            dispatch_via_native_router._tc_fixer = _tc_fixer
        available_tools = body.get("tools")
        before_tc = bool(msg.get("tool_calls"))
        before_content = str(msg.get("content") or "")[:120]
        msg = _tc_fixer.fix_message(msg, available_tools=available_tools)
        if msg.get("tool_calls") and not before_tc:
            try:
                _log_event(
                    {
                        "event": "tool_call_fixer_extracted",
                        "model": logical,
                        "names": [
                            (tc.get("function") or {}).get("name")
                            for tc in (msg.get("tool_calls") or [])
                        ][:8],
                        "from_content_prefix": before_content,
                    }
                )
            except Exception:
                pass
    except Exception as _tc_exc:
        try:
            _log_event(
                {
                    "event": "tool_call_fixer_failed",
                    "model": logical,
                    "error": f"{type(_tc_exc).__name__}: {_tc_exc}"[:240],
                }
            )
        except Exception:
            pass

    factual_tools = _requires_factual_tool_use(messages, routing=routing, model=gateway_model)
    if body.get("tools") and not msg.get("tool_calls"):
        synthesized = None
        if factual_tools:
            synthesized = _synthesize_file_tool_call(messages)
        if synthesized is None and factual_tools:
            synthesized = _synthesize_factual_terminal_call(messages)
        if synthesized is None:
            synthesized = _synthesize_image_generate_call(messages)
        if synthesized:
            msg = {**msg, "tool_calls": [synthesized], "content": None}
            for key in ("reasoning", "reasoning_content", "reasoning_details"):
                msg.pop(key, None)

    transmute_meta: Dict[str, Any] = {}
    # Run even after grammar_retry_no_tools (that path sets narrative_fast=True).
    # Skip only real RP. Explicit vault_search / vault narration still transmute.
    if (
        not msg.get("tool_calls")
        and not _roleplay_route_active(routing, gateway_model, messages)
        and not routing.get("no_transmute")
        and not routing.get("entity_skip_vault")
        and not body.get("_no_transmute")
    ):
        qinfo: Optional[Dict[str, Any]] = None
        try:
            import entity_pre_inject as epi

            nq = epi.narration_query(str(msg.get("content") or ""))
            uq = epi.user_vault_query(epi.last_user_text(messages))
            if uq:
                qinfo = uq
            elif nq:
                qinfo = {"query": nq, "roots": "vault", "max_hits": 8}
        except Exception:
            qinfo = None
        if qinfo and qinfo.get("query"):
            try:
                import entity_pre_inject as epi

                vs = epi.run_vault_search(
                    str(qinfo["query"]),
                    str(qinfo.get("roots") or "vault"),
                    int(qinfo.get("max_hits") or 8),
                )
                md = str(vs.get("markdown") or json.dumps(vs))[:3500]
                call_id = f"call_{uuid.uuid4().hex[:12]}"
                args = {
                    "query": qinfo["query"],
                    "roots": qinfo.get("roots") or "vault",
                }
                follow_msgs = list(messages or []) + [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": "vault_search",
                                    "arguments": json.dumps(args),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": "vault_search",
                        "content": md,
                    },
                ]
                _log_event(
                    {
                        "event": "narration_transmute_vault",
                        "query": str(qinfo["query"])[:80],
                        "hit_count": vs.get("hit_count"),
                    }
                )
                fres = _dispatch_payload(
                    {
                        "model": logical,
                        "messages": follow_msgs,
                        "max_tokens": min(int(body.get("max_tokens") or 256), 384),
                        "temperature": 0.2,
                        "stream": False,
                    }
                )
                if fres.get("status") == 200 and isinstance(fres.get("data"), dict):
                    data = fres["data"]
                    choice = (data.get("choices") or [{}])[0]
                    msg = dict(choice.get("message") or {})
                    transmute_meta = {
                        "narration_transmute": True,
                        "vault_query": str(qinfo["query"])[:80],
                        "vault_hits": vs.get("hit_count"),
                    }
                else:
                    msg = {**msg, "content": md, "tool_calls": None}
                    transmute_meta = {
                        "narration_transmute": True,
                        "followup_failed": True,
                        "vault_query": str(qinfo["query"])[:80],
                        "vault_hits": vs.get("hit_count"),
                    }
            except Exception as _tm_exc:
                try:
                    _log_event(
                        {
                            "event": "narration_transmute_fail",
                            "error": str(_tm_exc)[:160],
                        }
                    )
                except Exception:
                    pass
                msg = {
                    **msg,
                    "tool_calls": [
                        {
                            "id": f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": {
                                "name": "vault_search",
                                "arguments": json.dumps(
                                    {
                                        "query": qinfo["query"],
                                        "roots": qinfo.get("roots") or "vault",
                                    }
                                ),
                            },
                        }
                    ],
                    "content": None,
                }
                transmute_meta = {
                    "narration_transmute": True,
                    "emitted_tool_call": True,
                    "vault_query": str(qinfo["query"])[:80],
                }

    choice = {**choice, "message": msg}
    if msg.get("tool_calls"):
        gw_names = set(routing.get("atomic_gw_names") or [])
        rewritten = _rewrite_atomic_tool_calls(msg.get("tool_calls"), gw_names)
        if rewritten is not None:
            msg["tool_calls"] = rewritten
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
        slide = trim_meta.get("sliding_window") or {}
        prov["resurrection_trimmed"] = bool(slide.get("dropped_convo"))
    prov["token_ceiling"] = int(forward.get("max_tokens") or max_tokens or 2048)
    if transmute_meta:
        prov.update(transmute_meta)
    if routing.get("entity_preinjected"):
        prov["entity_preinjected"] = routing.get("entity_preinjected")
        prov["entity_inject_ms"] = routing.get("entity_inject_ms")

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
    """Session-id roleplay scan (not a Discord SDK call).

    Mouth adapters (Discord/WA/voice) already flattened the turn into OpenAI
    messages + optional phronesis body (chat_id/thread_id). This function only
    maps those IDs + prompt markers onto local_roleplay. New mouths must not
    add platform APIs here — stamp IDs in the body at the adapter.
    """
    body = body or {}
    try:
        from roleplay_route_guard import extract_phronesis_body

        phronesis = extract_phronesis_body(body)
    except Exception:
        phronesis = {}
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
        from discord_roleplay_connector import scan_messages_for_roleplay  # session IDs, not Discord SDK

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
    if "roleplay" in resolved_model.lower():
        force_roleplay = True

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
        "narrative_fast": False,
        "suppress_reasoning": False,
        "chat_id": str(phronesis.get("chat_id") or ""),
        "thread_id": str(phronesis.get("thread_id") or ""),
        "parent_channel_id": str(phronesis.get("parent_channel_id") or ""),
    }
    tool_fails = _count_recent_tool_failures(messages)
    routing["tool_fail_count"] = tool_fails
    # Roleplay / alice sandbox: never Grok-escalate on tool_fail or image keywords.
    if not force_roleplay:
        blob = _message_blob(messages).lower()
        image_timeout = any(
            k in blob for k in ("image_gen_timeout", "image timeout", "comfy timeout", "generation timed out")
        )
        if tool_fails > 1 or image_timeout:
            routing["escalation_tier"] = "T2"
            routing["tool_optimised_mode"] = True
            reasons = list(routing.get("reasons") or [])
            if tool_fails > 1:
                reasons.append(f"tool_fail_count={tool_fails}")
            if image_timeout:
                reasons.append("image_gen_timeout")
            routing["reasons"] = reasons
    nf = is_narrative_fast_path(messages, body, routing)
    routing["narrative_fast"] = nf
    routing["suppress_reasoning"] = nf
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
        tool_fail_count=int(route.get("tool_fail_count") or 0),
        explicit_grok_flag=False,
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


def build_rp_gpu_wait_message(reason: str = "") -> Tuple[str, int]:
    """RP-safe graceful wait under GPU contention (image lock / dual / 8090 down).

    Law 2026-07-27 / 2026-08-09 / 2026-08-12:
      - Never surface raw HTTP 503 to RP sandbox when GPU tenant is image.
      - Never offload RP narrative to free/Grok (local uncensored lane).
      - Prefer FIFO / wait-for-:8090 over any instant body.
      - Last-resort body is empty (Discord drops it). Never canned IC.

    Returns (empty_body, retry_after_sec).
    Network-free: uses local ETA tables + lock status only (no HTTP probes).
    """
    reason = (reason or "").strip()
    retry_s = 90
    lock_held = reason.startswith("image_lock") or "image_lock" in reason
    # Local ETA tables only (no forge/llm HTTP probes on the request path).
    try:
        import wait_visibility as wv

        eta_tab = getattr(wv, "ETA", {}) or {}
        cold = eta_tab.get("image_forge_cold") or (120, 240)
        hi_f = float(cold[1])
        retry_s = max(retry_s, int(hi_f))
    except Exception:
        pass
    try:
        from image_job_lock import status as _lock_status

        st = _lock_status() or {}
        if st.get("held"):
            lock_held = True
            ttl = st.get("ttl_remaining_s")
            if ttl is not None:
                try:
                    retry_s = max(retry_s, min(300, int(float(ttl)) + 20))
                except Exception:
                    pass
    except Exception:
        pass

    # Last-resort empty body only. Prefer waiting on FIFO / 8090 over posting.
    if "dual_tenant" in reason:
        retry_s = max(retry_s, 60)
    elif "8090_down" in reason:
        retry_s = max(45, min(retry_s, 120))
    return "", int(retry_s)


def _wait_8090_up(max_sec: int = 240) -> bool:
    """Block until local brain accepts TCP, or timeout. RP waits for real IC."""
    deadline = time.time() + max(5, int(max_sec))
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 8090), timeout=1.0):
                return True
        except OSError:
            time.sleep(3.0)
    return False


def _routing_is_roleplay(routing: Optional[Dict[str, Any]], model: str = "") -> bool:
    """True when this request must stay on local RP lane (no free/503 thrash)."""
    try:
        from escalation_router import is_roleplay_route

        if is_roleplay_route(routing or {}):
            return True
    except Exception:
        pass
    model_l = (model or "").lower()
    if "roleplay" in model_l or model_l.endswith("-rp"):
        return True
    task = str((routing or {}).get("task_type") or "").lower()
    return task in ("roleplay", "narrative", "rp")


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

    def _send_json(
        self,
        status: int,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            if value is not None:
                self.send_header(key, str(value))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _write_sse_event(self, payload: Dict[str, Any]) -> bool:
        try:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return False

    def _send_sse_chunk(
        self,
        model: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        finish_reason: str = "stop",
        *,
        chunk_chars: int = 96,
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
                if not self._write_sse_event(chunk):
                    return False
            elif content:
                done_reason = finish_reason or "stop"
                step = max(32, int(chunk_chars))
                for offset in range(0, len(content), step):
                    piece = content[offset: offset + step]
                    chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                    }
                    if not self._write_sse_event(chunk):
                        return False
            else:
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                }
                done_reason = finish_reason or "stop"
                if not self._write_sse_event(chunk):
                    return False
            done = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": done_reason}],
            }
            if not self._write_sse_event(done):
                return False
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
            breaker_states: Dict[str, Any] = {}
            with _breakers_lock:
                for port, br in _breakers.items():
                    breaker_states[str(port)] = br.snapshot() if hasattr(br, "snapshot") else br.state
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
                "qwythos_primer": bool(_load_qwythos_primer()),
                "atomic_tools": list(ATOMIC_TOOL_NAMES),
                "golden_bank_n": len(_load_golden_bank()),
                "golden_bank_path": str(GOLDEN_BANK_PATH),
                "entity_pre_inject": True,
                "narration_transmute": True,
            }
            try:
                payload["stack"] = matrix
                if LRU_ROUTER_STATE.is_file():
                    raw_ld = json.loads(LRU_ROUTER_STATE.read_text(encoding="utf-8"))
                    # A2 health truth (2026-07-19): never present stale LRU as "live traffic".
                    # Consumers used last_dispatch + last_model (e.g. MythoMax) as if current.
                    # Research: readiness payloads must distinguish last-event vs live state.
                    ld = dict(raw_ld) if isinstance(raw_ld, dict) else {"raw": raw_ld}
                    ts_raw = str(ld.get("last_dispatch") or ld.get("ts") or "")
                    age_sec = None
                    try:
                        from datetime import datetime, timezone

                        ts_clean = ts_raw.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(ts_clean)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        age_sec = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
                    except Exception:
                        age_sec = None
                    stale_after = 6 * 3600  # 6h
                    ld["age_sec"] = age_sec
                    ld["stale"] = bool(age_sec is None or age_sec > stale_after)
                    ld["stale_after_sec"] = stale_after
                    ld["resident_note"] = (
                        "last_dispatch is last routed event, not necessarily the GGUF "
                        "currently loaded on :8090 (unified_8090 / Qwythos primary)"
                    )
                    # Prefer stack matrix model truth over frozen LRU last_model
                    try:
                        live_model = (matrix.get("unified_model") or matrix.get("model")
                                      or matrix.get("loaded") or "")
                        if live_model:
                            ld["resident_model_hint"] = live_model
                    except Exception:
                        pass
                    payload["last_dispatch"] = ld
                    payload["last_dispatch_stale"] = ld["stale"]
            except Exception:
                pass
            try:
                from inference_queue import get_inference_queue

                q = get_inference_queue().snapshot()
                payload["inference_queue"] = {
                    "waiting_count": q.get("waiting_count"),
                    "active": q.get("active"),
                    "avg_latency_sec": q.get("avg_latency_sec"),
                    "fifo_lanes": {
                        "roleplay": q["fifo_lanes"]["roleplay"]["count"],
                        "normal": q["fifo_lanes"]["normal"]["count"],
                    },
                }
            except Exception:
                pass
            self._send_json(200, payload)
            return
        if path in ("/v1/queue", "/queue"):
            try:
                from inference_queue import get_inference_queue

                self._send_json(200, get_inference_queue().snapshot())
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if path.startswith("/v1/queue/") or path.startswith("/queue/"):
            req_id = path.rsplit("/", 1)[-1].strip()
            try:
                from inference_queue import get_inference_queue

                entry = get_inference_queue().get(req_id)
                if entry is None:
                    self._send_json(404, {"error": "queue_entry_not_found", "id": req_id})
                else:
                    self._send_json(200, entry)
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
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
        # W2-P1 lab: circuit status (localhost only)
        if path in ("/v1/admin/circuit", "/admin/circuit"):
            if not self._client_is_loopback():
                self._send_json(403, {"error": "loopback_only"})
                return
            with _breakers_lock:
                ports = {str(p): br.snapshot() for p, br in _breakers.items()}
            # always include 8090 even if never touched
            if "8090" not in ports:
                ports["8090"] = _get_breaker(8090).snapshot()
            self._send_json(200, {"circuit_breakers": ports, "ts": _utc_now()})
            return
        self._send_json(404, {"error": "not_found"})

    def _client_is_loopback(self) -> bool:
        try:
            host = (self.client_address[0] or "").strip()
            return host in ("127.0.0.1", "::1", "localhost")
        except Exception:
            return False

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        # W2-P1 lab: force-open / force-close circuit (loopback only)
        if path in ("/v1/admin/circuit", "/admin/circuit"):
            if not self._client_is_loopback():
                self._send_json(403, {"error": "loopback_only"})
                return
            try:
                body = self._read_json()
            except Exception as exc:
                self._send_json(400, {"error": f"invalid JSON: {exc}"})
                return
            if body.get("__error__"):
                return
            action = str(body.get("action") or "").strip().lower()
            try:
                port = int(body.get("port") or 8090)
            except Exception:
                port = 8090
            br = _get_breaker(port)
            if action in ("open", "force_open"):
                br.force_open()
            elif action in ("close", "force_close", "reset"):
                br.force_close()
            elif action in ("status", "", "get"):
                pass
            else:
                self._send_json(400, {"error": "action must be open|close|status"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "port": port,
                    "action": action or "status",
                    "breaker": br.snapshot(),
                    "ts": _utc_now(),
                },
            )
            return
        if path in ("/v1/trim_inspect", "/trim_inspect"):
            # Loopback-only. Trim + token ceiling. Never calls llama-server :8090.
            if not self._client_is_loopback():
                self._send_json(403, {"error": "loopback_only"})
                return
            try:
                body = self._read_json()
            except Exception as exc:
                self._send_json(400, {"error": f"invalid JSON: {exc}"})
                return
            if body.get("__error__"):
                return
            model = str(body.get("model") or "phronesis-sovereign-auto")
            messages = body.get("messages") or []
            routing = resolve_roleplay_routing(messages, model, body)
            model = str(routing.get("model") or model)
            if not (routing.get("narrative_fast") or routing.get("roleplay") or routing.get("is_roleplay")):
                messages = _inject_qwythos_primer(messages, routing)
                messages, _ent = _inject_entity_context(messages, routing)
            try:
                trimmed, trim_meta = trim_messages_tier_aware(messages, model)
            except Exception as exc:
                self._send_json(400, {"error": f"trim failed: {exc}"})
                return
            narrative_fast = is_narrative_fast_path(messages, body, routing)
            tool_passthrough = _request_needs_tool_passthrough(body, messages)
            factual_tools = _requires_factual_tool_use(messages, routing=routing, model=model)
            requested_max = int(body.get("max_tokens") or 2048)
            cap = 4096 if (tool_passthrough or factual_tools) else 2048
            max_tokens = min(requested_max, cap)
            if not narrative_fast:
                max_tokens = max(max_tokens, min(2048, cap))
            elif narrative_fast:
                max_tokens = min(max_tokens, 1536)
            slide = (trim_meta or {}).get("sliding_window") or {}
            self._send_json(
                200,
                {
                    "ok": True,
                    "llama_touched": False,
                    "kept_n": len(trimmed),
                    "kept_roles": [str(m.get("role")) for m in trimmed],
                    "anchor_n": int(slide.get("anchor_n") or 0),
                    "tail_n": int(slide.get("tail_n") or 0),
                    "dropped_convo": int(slide.get("dropped_convo") or 0),
                    "phronesis_provenance": {
                        "token_ceiling": int(max_tokens),
                        "resurrection_trimmed": bool(slide.get("dropped_convo")),
                        "sliding_window": slide,
                        "context_trim": {
                            "trimmed": bool((trim_meta or {}).get("trimmed")),
                            "original_message_count": (trim_meta or {}).get("original_message_count"),
                            "final_message_count": (trim_meta or {}).get("final_message_count"),
                        },
                    },
                },
            )
            return
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
        routing["atomic_gw_names"] = sorted(_tool_schema_names(body.get("tools")))
        if not (routing.get("narrative_fast") or routing.get("roleplay") or routing.get("is_roleplay")):
            messages = _inject_qwythos_primer(messages, routing)
            # Lean 9B path: primer + entity + last N turns + tool schemas.
            # Golden fewshot is opt-in (HERMES_GOLDEN_FEWSHOT=1) — it burned
            # context tokens duplicating the primer's tool-call contract.
            if os.environ.get("HERMES_GOLDEN_FEWSHOT", "").strip() in ("1", "true", "yes"):
                messages = _inject_golden_fewshot(messages, routing)
            messages, _ent = _inject_entity_context(messages, routing)
            if _ent.get("injected"):
                routing["entity_preinjected"] = _ent.get("injected")
                routing["entity_skip_vault"] = bool(_ent.get("skip_vault"))
                routing["entity_inject_ms"] = _ent.get("ms")
            body["tools"] = _merge_atomic_tools(body.get("tools"))
        if routing.get("tool_optimised_mode"):
            tier = str(routing.get("escalation_tier") or "T2")
            messages = _inject_tool_optimised_mode(messages, tier=tier)

        tools_reserve = _estimate_tools_tokens(body.get("tools")) if body.get("tools") else 0
        pressure_reserve = _fifo_pressure_reserve_tokens()
        augment_meta: Dict[str, Any] = {}
        try:
            trimmed_messages, trim_meta = trim_messages_tier_aware(
                messages,
                model,
                extra_reserve_tokens=tools_reserve + pressure_reserve,
            )
            if pressure_reserve:
                trim_meta["fifo_pressure_reserve"] = pressure_reserve
            try:
                from escalation_router import maybe_augment_messages_with_context

                pre_prompt = messages_to_prompt(trimmed_messages)
                trimmed_messages, augment_meta = maybe_augment_messages_with_context(
                    trimmed_messages, pre_prompt, routing,
                )
                if augment_meta.get("augmented"):
                    trim_meta = {**trim_meta, "fleet_context_augment": augment_meta}
            except Exception as aug_exc:
                _log_event({"event": "fleet_augment_skip", "error": str(aug_exc)})
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
        queue_ticket = None
        queue_headers: Dict[str, str] = {}
        result: Dict[str, Any] = {}
        proactive_handled = False

        if not stream:
            try:
                from escalation_router import try_proactive_offload_dispatch

                req_headers = {
                    k: v
                    for k, v in self.headers.items()
                    if k.lower().startswith("x-phronesis-")
                }
                proactive_result = try_proactive_offload_dispatch(
                    prompt,
                    routing,
                    trimmed_messages,
                    body,
                    headers=req_headers,
                )
                if proactive_result.get("success"):
                    result = proactive_result
                    proactive_handled = True
                    prov = result.setdefault("provenance", {})
                    prov["context_trim"] = trim_meta
                    _log_event({
                        "event": "proactive_offload_ok",
                        "model": model,
                        "tier": result.get("tier"),
                        "backend": prov.get("selected_backend"),
                        "routing_mode": prov.get("routing_mode"),
                        "reasons": (result.get("classification") or {}).get("reasons"),
                    })
                elif proactive_result.get("skipped") not in (None, "proactive_disabled"):
                    _log_event({
                        "event": "proactive_offload_skip",
                        "skipped": proactive_result.get("skipped"),
                        "reasons": proactive_result.get("reasons"),
                    })
            except Exception as pro_exc:
                _log_event({"event": "proactive_offload_error", "error": str(pro_exc)})

        use_native = _unified_router_up()
        prefer_fleet_now = False
        prefer_fleet_reason = ""
        # Hard free-fleet path under local contention: skip GPU FIFO so text
        # work does not pile onto dead/contended :8090 (Grok-token-outage path).
        try:
            from inference_queue import should_prefer_fleet_offload
            from escalation_router import is_roleplay_route

            prefer_fleet_now, prefer_fleet_reason = should_prefer_fleet_offload()
            # RP stays on local FIFO even under contention. Jeff prefers a real
            # local completion (full scene context) over an instant wait line.
            if prefer_fleet_now and is_roleplay_route(routing):
                _log_event(
                    {
                        "event": "rp_wait_local_fifo",
                        "reason": prefer_fleet_reason,
                        "stream": bool(stream),
                        "model": model,
                    }
                )
            # Stream AND non-stream: under prefer_fleet, skip local GPU FIFO.
            # Voice/agent streaming previously ALWAYS hit FIFO (not stream gate),
            # so Discord voice waited minutes and produced zero TTS clauses.
            if prefer_fleet_now and not is_roleplay_route(routing):
                # Attempt proactive free offload again if first pass skipped local_first
                if not proactive_handled and not stream:
                    try:
                        from escalation_router import try_proactive_offload_dispatch

                        req_headers = {
                            k: v
                            for k, v in self.headers.items()
                            if k.lower().startswith("x-phronesis-")
                        }
                        # Stamp skip so classify/policy sees contention
                        routing = {
                            **routing,
                            "prefer_fleet": True,
                            "prefer_fleet_reason": prefer_fleet_reason,
                            "local_fail_reason": prefer_fleet_reason,
                        }
                        pr2 = try_proactive_offload_dispatch(
                            prompt,
                            routing,
                            trimmed_messages,
                            body,
                            headers=req_headers,
                        )
                        if pr2.get("success"):
                            result = pr2
                            proactive_handled = True
                            prov = result.setdefault("provenance", {})
                            prov["context_trim"] = trim_meta
                            prov["prefer_fleet_reason"] = prefer_fleet_reason
                            prov["hard_skip_local_fifo"] = True
                            _log_event(
                                {
                                    "event": "prefer_fleet_skip_fifo_ok",
                                    "reason": prefer_fleet_reason,
                                    "backend": prov.get("selected_backend"),
                                }
                            )
                    except Exception as pf_exc:
                        _log_event(
                            {
                                "event": "prefer_fleet_skip_fifo_error",
                                "error": str(pf_exc)[:200],
                                "reason": prefer_fleet_reason,
                            }
                        )
                if not proactive_handled:
                    # Fast-fail local → free via resolve_post_local without FIFO wait
                    # (works for stream=True agent turns used by Discord voice)
                    use_native = False
                    routing = {
                        **routing,
                        "prefer_fleet": True,
                        "prefer_fleet_reason": prefer_fleet_reason,
                        "local_fail_reason": prefer_fleet_reason,
                    }
                    _log_event(
                        {
                            "event": "prefer_fleet_bypass_fifo",
                            "reason": prefer_fleet_reason,
                            "stream": bool(stream),
                            "note": "skip GPU queue; free-before-grok ladder",
                        }
                    )
        except Exception as pref_exc:
            _log_event({"event": "prefer_fleet_check_error", "error": str(pref_exc)[:160]})

        if use_native and not proactive_handled:
            try:
                from inference_queue import (
                    BackgroundDeferred,
                    MAX_QUEUE_WAIT_SEC,
                    QueueAdmissionRejected,
                    QueueWaitTimeout,
                    get_inference_queue,
                )

                caller = _resolve_queue_caller(self, routing, body)
                req_hdr = (self.headers.get("X-Phronesis-Request-Id") or "").strip() or None
                queue_ticket = get_inference_queue().acquire(
                    model=model,
                    caller=caller,
                    request_id=req_hdr,
                    routing=routing,
                    prompt_tokens_est=int(trim_meta.get("final_tokens_estimate") or 0) or None,
                    message_count=len(trimmed_messages),
                    max_tokens=int(body.get("max_tokens") or 0) or None,
                )
                queue_headers = {
                    "X-Phronesis-Queue-Id": queue_ticket.id,
                    "X-Phronesis-Queue-Lane": "roleplay" if queue_ticket.lane == 0 else "normal",
                    "X-Phronesis-Queue-Position": str(queue_ticket.position),
                    "X-Phronesis-Queue-Wait-Sec": str(queue_ticket.wait_sec),
                }
                if queue_ticket.eta_sec is not None:
                    queue_headers["X-Phronesis-Queue-Eta-Sec"] = str(queue_ticket.eta_sec)
                _log_event({
                    "event": "fifo_acquire",
                    "id": queue_ticket.id,
                    "model": model,
                    "caller": caller,
                    "lane": queue_ticket.lane,
                    "wait_sec": queue_ticket.wait_sec,
                })
            except QueueWaitTimeout as qexc:
                ent = qexc.entry
                _log_event({
                    "event": "fifo_wait_timeout",
                    "id": ent.id,
                    "model": model,
                    "position": ent.position,
                    "lane": ent.lane,
                })
                # Overnight harden 2026-08-10: RP must not get raw 503 → free fallback.
                if _routing_is_roleplay(routing, model):
                    wait_msg, retry_s = build_rp_gpu_wait_message(
                        f"fifo_wait_timeout:pos={ent.position}"
                    )
                    _log_event({
                        "event": "rp_graceful_wait",
                        "reason": "fifo_wait_timeout",
                        "retry_after_sec": retry_s,
                        "model": model,
                    })
                    hdrs = {
                        "Retry-After": str(int(retry_s)),
                        "X-Phronesis-Wait": "gpu_fifo",
                        "X-Phronesis-Queue-Id": ent.id,
                    }
                    if stream:
                        self._send_sse_chunk(model, wait_msg)
                    else:
                        self._send_json(
                            200,
                            openai_chat_response(
                                model,
                                wait_msg,
                                extra={
                                    "path": "proxy_8091_rp_graceful_wait",
                                    "graceful_wait": True,
                                    "prefer_fleet_reason": "fifo_wait_timeout",
                                    "retry_after_sec": retry_s,
                                },
                            ),
                            extra_headers=hdrs,
                        )
                    return
                status, err = openai_error(
                    503,
                    f"FIFO wait timeout after {MAX_QUEUE_WAIT_SEC}s (position {ent.position})",
                )
                err["phronesis_queue"] = ent.to_dict()
                self._send_json(status, err, extra_headers={"X-Phronesis-Queue-Id": ent.id})
                return
            except BackgroundDeferred as qexc:
                _log_event({
                    "event": "fifo_background_deferred",
                    "model": model,
                    "reason": qexc.reason,
                    "retry_after_sec": qexc.retry_after_sec,
                })
                if _routing_is_roleplay(routing, model):
                    wait_msg, retry_s = build_rp_gpu_wait_message(
                        f"background_deferred:{qexc.reason}"
                    )
                    retry_s = max(int(retry_s), int(getattr(qexc, "retry_after_sec", 0) or 0))
                    _log_event({
                        "event": "rp_graceful_wait",
                        "reason": "background_deferred",
                        "retry_after_sec": retry_s,
                        "model": model,
                    })
                    if stream:
                        self._send_sse_chunk(model, wait_msg)
                    else:
                        self._send_json(
                            200,
                            openai_chat_response(
                                model,
                                wait_msg,
                                extra={
                                    "path": "proxy_8091_rp_graceful_wait",
                                    "graceful_wait": True,
                                    "prefer_fleet_reason": "background_deferred",
                                    "retry_after_sec": retry_s,
                                },
                            ),
                            extra_headers={"Retry-After": str(int(retry_s))},
                        )
                    return
                status, err = openai_error(
                    503,
                    f"Inference deferred for background work ({qexc.reason})",
                )
                err["phronesis_defer"] = {
                    "reason": qexc.reason,
                    "retry_after_sec": qexc.retry_after_sec,
                }
                self._send_json(
                    status,
                    err,
                    extra_headers={"Retry-After": str(qexc.retry_after_sec)},
                )
                return
            except QueueAdmissionRejected as qexc:
                _log_event({
                    "event": "fifo_admission_rejected",
                    "model": model,
                    "reason": qexc.reason,
                    "waiting_count": qexc.waiting_count,
                    "retry_after_sec": qexc.retry_after_sec,
                })
                if _routing_is_roleplay(routing, model):
                    wait_msg, retry_s = build_rp_gpu_wait_message(
                        f"fifo_admission:{qexc.reason}"
                    )
                    retry_s = max(int(retry_s), int(getattr(qexc, "retry_after_sec", 0) or 0))
                    _log_event({
                        "event": "rp_graceful_wait",
                        "reason": "fifo_admission_rejected",
                        "retry_after_sec": retry_s,
                        "model": model,
                    })
                    if stream:
                        self._send_sse_chunk(model, wait_msg)
                    else:
                        self._send_json(
                            200,
                            openai_chat_response(
                                model,
                                wait_msg,
                                extra={
                                    "path": "proxy_8091_rp_graceful_wait",
                                    "graceful_wait": True,
                                    "prefer_fleet_reason": "fifo_admission_rejected",
                                    "retry_after_sec": retry_s,
                                },
                            ),
                            extra_headers={"Retry-After": str(int(retry_s))},
                        )
                    return
                status, err = openai_error(
                    503,
                    f"GPU FIFO at capacity ({qexc.waiting_count} ahead); retry later",
                )
                err["phronesis_admission"] = {
                    "reason": qexc.reason,
                    "waiting_count": qexc.waiting_count,
                    "retry_after_sec": qexc.retry_after_sec,
                }
                self._send_json(
                    status,
                    err,
                    extra_headers={"Retry-After": str(qexc.retry_after_sec)},
                )
                return
            except Exception as qexc:
                _log_event({"event": "fifo_acquire_error", "error": str(qexc), "model": model})

        try:
            from sovereign_preflight import ensure_sovereign_router

            if not ensure_sovereign_router():
                _log_event({"event": "router_preflight_failed", "model": model})
        except Exception as pre_exc:
            _log_event({"event": "router_preflight_exception", "error": str(pre_exc)})

        if not proactive_handled:
            try:
                if prefer_fleet_now and not use_native:
                    # Contended/down local: do not call bridge/native ? synthetic local fail
                    # then free-before-grok ladder via resolve_post_local_dispatch.
                    result = {
                        "success": False,
                        "error": f"prefer_fleet_bypass:{prefer_fleet_reason}",
                        "provenance": {
                            "path": "proxy_8091",
                            "selected_backend": "skipped_local",
                            "prefer_fleet_reason": prefer_fleet_reason,
                            "hard_skip_local_fifo": True,
                        },
                    }
                    routing = {
                        **routing,
                        "path": "proxy_8091",
                        "local_fail_reason": prefer_fleet_reason or "prefer_fleet",
                        "prefer_fleet": True,
                    }
                elif use_native:
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
                # W2-P1: stamp proxy path + live circuit state before escalation
                try:
                    br_snap = _get_breaker(8090).snapshot()
                    prov0 = result.setdefault("provenance", {})
                    prov0["path"] = "proxy_8091"
                    prov0["circuit_8090"] = br_snap.get("state")
                    prov0["circuit_force_open"] = bool(br_snap.get("force_open"))
                    if not result.get("success"):
                        routing = {
                            **routing,
                            "path": "proxy_8091",
                            "circuit_8090": br_snap.get("state"),
                            "local_fail_reason": str(
                                result.get("error") or result.get("response") or ""
                            )[:300],
                        }
                except Exception:
                    routing = {**routing, "path": "proxy_8091"}
                try:
                    from escalation_router import resolve_post_local_dispatch

                    if augment_meta.get("augmented"):
                        result.setdefault("provenance", {})["context_augment"] = augment_meta
                    result = resolve_post_local_dispatch(prompt, routing, result)
                except Exception as esc_exc:
                    _log_event({"event": "post_local_escalation_error", "error": str(esc_exc)})
                # RP: wait for :8090 and retry local once. No instant canned line.
                if _routing_is_roleplay(routing, model) and not result.get("success"):
                    _log_event({
                        "event": "rp_wait_8090_retry",
                        "model": model,
                        "detail": str(result.get("error") or result.get("response") or "")[:120],
                    })
                    if _wait_8090_up(240):
                        try:
                            result = dispatch_via_native_router(
                                body,
                                trimmed_messages,
                                model,
                                routing=routing,
                                trim_meta=trim_meta,
                            )
                            try:
                                from escalation_router import resolve_post_local_dispatch as _rpl

                                result = _rpl(prompt, routing, result)
                            except Exception:
                                pass
                            _log_event({
                                "event": "rp_wait_8090_retry_done",
                                "ok": bool(result.get("success")),
                                "model": model,
                            })
                        except Exception as retry_exc:
                            _log_event({
                                "event": "rp_wait_8090_retry_error",
                                "error": str(retry_exc)[:160],
                            })
                # Ensure path stamped on final result
                try:
                    result.setdefault("provenance", {})["path"] = "proxy_8091"
                except Exception:
                    pass
            except Exception as exc:
                _log_event({"event": "dispatch_exception", "error": str(exc), "model": model})
                try:
                    from sovereign_failure_taxonomy import classify_dispatch_failure

                    fm = classify_dispatch_failure(str(exc))
                except Exception:
                    fm = {
                        "http_status": 503,
                        "error_type": "server_error",
                        "failure_class": "unknown",
                        "retryable": True,
                    }
                status, err = openai_error(
                    int(fm.get("http_status") or 503),
                    f"dispatch failed: {exc}",
                    str(fm.get("error_type") or "server_error"),
                )
                err["phronesis_failure"] = {
                    "failure_class": fm.get("failure_class"),
                    "retryable": fm.get("retryable"),
                }
                if queue_ticket is not None:
                    err["phronesis_queue"] = _queue_ticket_dict(queue_ticket)
                self._send_json(status, err, extra_headers=queue_headers or None)
                return
            finally:
                if queue_ticket is not None:
                    try:
                        from inference_queue import get_inference_queue

                        latency = round(time.time() - started, 2)
                        get_inference_queue().release(
                            queue_ticket.id,
                            success=bool(result.get("success")),
                            error=None if result.get("success") else str(result.get("response") or "dispatch_failed"),
                            latency_sec=latency if result.get("success") else None,
                        )
                    except Exception:
                        pass

        latency = round(time.time() - started, 2)
        prov = result.get("provenance") or {}

        if result.get("escalation") and not result.get("success"):
            msg = (
                "[GROK ESCALATION RECOMMENDED] "
                + str(prov.get("escalation_reason") or result.get("response", ""))
            )
            _log_event({"event": "escalation", "model": model, "triggers": prov.get("escalation_triggers")})
            # RP: never escalate to free/Grok via 503 — soft-wait local only.
            if _routing_is_roleplay(routing, model):
                wait_msg, retry_s = build_rp_gpu_wait_message(
                    str(prov.get("escalation_reason") or "escalation_blocked_rp")
                )
                _log_event({
                    "event": "rp_graceful_wait",
                    "reason": "escalation_blocked_rp",
                    "retry_after_sec": retry_s,
                    "model": model,
                })
                if stream:
                    self._send_sse_chunk(model, wait_msg)
                else:
                    self._send_json(
                        200,
                        openai_chat_response(
                            model,
                            wait_msg,
                            extra={
                                "path": "proxy_8091_rp_graceful_wait",
                                "graceful_wait": True,
                                "escalation_blocked": True,
                                "retry_after_sec": retry_s,
                            },
                        ),
                        extra_headers={"Retry-After": str(int(retry_s))},
                    )
                return
            # Escalation remaining is capacity-ish: client may failover providers.
            # Prefer 503 only when not a permanent local template error.
            try:
                from sovereign_failure_taxonomy import classify_dispatch_failure

                fm = classify_dispatch_failure(msg, provenance=prov)
                esc_status = int(fm.get("http_status") or 503)
                esc_type = str(fm.get("error_type") or "escalation_required")
                if fm.get("failure_class") != "permanent":
                    esc_status = 503
                    esc_type = "escalation_required"
            except Exception:
                esc_status, esc_type = 503, "escalation_required"
            status, err = openai_error(esc_status, msg, esc_type)
            if queue_ticket is not None:
                err["phronesis_queue"] = _queue_ticket_dict(queue_ticket)
            self._send_json(status, err, extra_headers=queue_headers or None)
            return

        if not result.get("success"):
            msg = result.get("response") or "local dispatch failed"
            # Overnight harden 2026-08-10: RP local fail → IC soft-wait (200), never
            # raw 503 that drives agent openrouter/free fallback on ERP lanes.
            if _routing_is_roleplay(routing, model):
                fail_reason = str(
                    (prov or {}).get("local_fail_reason")
                    or (prov or {}).get("prefer_fleet_reason")
                    or msg
                    or "local_dispatch_failed"
                )[:160]
                wait_msg, retry_s = build_rp_gpu_wait_message(fail_reason)
                _log_event({
                    "event": "rp_graceful_wait",
                    "reason": "local_dispatch_failed",
                    "detail": fail_reason[:120],
                    "retry_after_sec": retry_s,
                    "model": model,
                    "stream": bool(stream),
                })
                hdrs = {
                    "Retry-After": str(int(retry_s)),
                    "X-Phronesis-Wait": "local_fail",
                    "X-Phronesis-Wait-Reason": fail_reason[:120],
                }
                if queue_headers:
                    hdrs.update(queue_headers)
                if stream:
                    self._send_sse_chunk(model, wait_msg)
                else:
                    self._send_json(
                        200,
                        openai_chat_response(
                            model,
                            wait_msg,
                            extra={
                                "path": "proxy_8091_rp_graceful_wait",
                                "graceful_wait": True,
                                "not_error": True,
                                "prefer_fleet_reason": fail_reason,
                                "retry_after_sec": retry_s,
                                "local_fail_soft": True,
                            },
                        ),
                        extra_headers=hdrs,
                    )
                return
            try:
                from sovereign_failure_taxonomy import classify_dispatch_failure

                fm = classify_dispatch_failure(str(msg), provenance=prov)
                # Prefer explicit client_http_status from native path if present
                if result.get("client_http_status"):
                    fm["http_status"] = int(result["client_http_status"])
                if result.get("failure_class"):
                    fm["failure_class"] = result["failure_class"]
            except Exception:
                fm = {
                    "http_status": 503,
                    "error_type": "server_error",
                    "failure_class": "unknown",
                    "retryable": True,
                }
            status = int(fm.get("http_status") or 503)
            err_type = str(fm.get("error_type") or "server_error")
            _log_event({
                "event": "dispatch_fail",
                "model": model,
                "attempts": result.get("attempts"),
                "failure_class": fm.get("failure_class"),
                "client_http_status": status,
                "retryable": fm.get("retryable"),
            })
            status, err = openai_error(status, msg, err_type)
            err["phronesis_failure"] = {
                "failure_class": fm.get("failure_class"),
                "retryable": fm.get("retryable"),
            }
            if queue_ticket is not None:
                err["phronesis_queue"] = _queue_ticket_dict(queue_ticket)
            self._send_json(status, err, extra_headers=queue_headers or None)
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
            "token_ceiling": int(prov.get("token_ceiling") or 2048),
            "resurrection_trimmed": bool(
                prov.get("resurrection_trimmed")
                or ((trim_meta.get("sliding_window") or {}).get("dropped_convo") if trim_meta else 0)
            ),
            "narrative_fast": bool(routing.get("narrative_fast") or result.get("narrative_fast")),
            "suppress_reasoning": bool(
                routing.get("suppress_reasoning") or result.get("narrative_fast")
            ),
            "native_passthrough": bool(prov.get("native_passthrough")),
            "tool_passthrough": bool(prov.get("tool_passthrough") or result.get("tool_calls")),
            "entity_preinjected": prov.get("entity_preinjected") or routing.get("entity_preinjected"),
            "entity_inject_ms": prov.get("entity_inject_ms") or routing.get("entity_inject_ms"),
            "narration_transmute": bool(prov.get("narration_transmute")),
            "vault_query": prov.get("vault_query"),
            "vault_hits": prov.get("vault_hits"),
        }
        usage_in = usage_out = 0
        openai_resp = result.get("openai_response")
        if isinstance(openai_resp, dict):
            usage = openai_resp.get("usage") or {}
            usage_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            usage_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        if not usage_in and not usage_out:
            usage_in = int(trim_meta.get("final_tokens_estimate") or estimate_tokens(messages_to_prompt(messages)))
            usage_out = max(50, len(content) // 4)

        _log_event({
            "event": "dispatch_ok",
            "model": model,
            "input_tokens": usage_in,
            "output_tokens": usage_out,
            **{k: v for k, v in extra.items() if k != "context_trim"},
        })
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
            "input_tokens": usage_in,
            "output_tokens": usage_out,
            "usage": {
                "prompt_tokens": usage_in,
                "completion_tokens": usage_out,
                "total_tokens": usage_in + usage_out,
            },
            # Phase 1-2 decision-log hygiene (2026-07-19): align with decision_log_schema
            "policy_version": "hybrid-local-grok-2026-07-17",
            "routing_reasons": [
                r for r in [
                    f"task_type={routing.get('task_type') or resolve_task_type(model)}",
                    f"tier={result.get('tier')}",
                    f"backend={prov.get('selected_backend')}",
                    f"router_mode=unified_8090" if True else "",
                    "uncensored" if prov.get("uncensored_route") else "",
                    "force_roleplay" if routing.get("force_roleplay") else "",
                ] if r
            ],
            "failure_class": None,
            # W3-P3 continuous fields
            "path": prov.get("path") or "proxy_8091",
            "provider_id": prov.get("provider_id") or result.get("provider_id"),
            "tier_bucket": prov.get("tier_bucket"),
            "role": (prov.get("backend_policy") or {}).get("role") if isinstance(prov.get("backend_policy"), dict) else None,
            "success": True,
        })
        # W3-P3: dual-write continuous completion stamp (never block inference)
        try:
            from router_thrift_rollup import append_completion_provenance, tier_bucket as _tb  # type: ignore
        except Exception:
            try:
                import sys as _sys
                from pathlib import Path as _P
                _sp = str(_P(r"D:\HermesData\scripts"))
                if _sp not in _sys.path:
                    _sys.path.insert(0, _sp)
                from router_thrift_rollup import append_completion_provenance
            except Exception:
                append_completion_provenance = None  # type: ignore
        if append_completion_provenance is not None:
            try:
                from router_backend_policy import tier_bucket as _tier_bucket
            except Exception:
                _tier_bucket = None  # type: ignore
            backend_s = str(prov.get("selected_backend") or result.get("tier") or "")
            pid_s = str(prov.get("provider_id") or result.get("provider_id") or "")
            model_s = str(resolved_model or model or "")
            tb = prov.get("tier_bucket")
            if not tb and _tier_bucket:
                try:
                    tb = _tier_bucket(backend_s, provider_id=pid_s, model=model_s)
                except Exception:
                    tb = None
            role_s = None
            bp = prov.get("backend_policy")
            if isinstance(bp, dict):
                role_s = bp.get("role")
            append_completion_provenance({
                "event": "completion_ok",
                "success": True,
                "path": prov.get("path") or "proxy_8091",
                "backend": backend_s,
                "selected_backend": backend_s,
                "provider_id": pid_s,
                "model": model_s,
                "tier": result.get("tier"),
                "tier_bucket": tb,
                "role": role_s,
                "task_type": routing.get("task_type") or resolve_task_type(model),
                "latency_sec": latency,
                "input_tokens": usage_in,
                "output_tokens": usage_out,
            })
        # Keep /health last_dispatch live (not frozen LRU from pre-unified path).
        _touch_last_dispatch(
            logical_model=str(resolved_model or model or ""),
            task_type=str(routing.get("task_type") or resolve_task_type(model) or ""),
            tier=str(result.get("tier") or ""),
            backend=str(prov.get("selected_backend") or ""),
        )
        try:
            backend = str(prov.get("selected_backend") or "native_8090")
            if backend in ("native_8090", "native_8090_cached", "vault_v0.11", "ollama"):
                from sovereign_usage_savings import record_local_usage

                record_local_usage(
                    input_tokens=usage_in,
                    output_tokens=usage_out,
                    backend=backend,
                    model=str(resolved_model or model),
                    source="proxy",
                )
        except Exception:
            pass

        def _async_checkpoint() -> None:
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

        threading.Thread(target=_async_checkpoint, daemon=True, name="sovereign-checkpoint").start()

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
            if queue_ticket is not None:
                out["phronesis_queue"] = _queue_ticket_dict(queue_ticket)
            msg = (out.get("choices") or [{}])[0].setdefault("message", {})
            visible = content or _assistant_visible_content(msg, allow_reasoning_fallback=True)
            if visible:
                msg["content"] = visible
            if result.get("narrative_fast") or visible:
                for key in ("reasoning", "reasoning_content", "reasoning_details"):
                    msg.pop(key, None)
            self._send_json(200, out, extra_headers=queue_headers or None)
            return

        success_payload = openai_chat_response(report_model, content, extra=extra)
        if queue_ticket is not None:
            success_payload["phronesis_queue"] = _queue_ticket_dict(queue_ticket)
        self._send_json(200, success_payload, extra_headers=queue_headers or None)


def _self_test_trim() -> Dict[str, Any]:
    big = "x" * 12000
    messages = [{"role": "system", "content": "You are Hermes."}]
    for i in range(30):
        messages.append({"role": "user", "content": f"Turn {i}: {big}"})
        messages.append({"role": "assistant", "content": f"Ack {i}"})
    trimmed, meta = trim_messages_tier_aware(messages, "phronesis-sovereign-code")
    prompt = messages_to_prompt(trimmed)

    # Regression: oversized single user turn must not crash on non_system.index()
    # Must exceed local_hot input cap (~24k tok ~ 72k chars at len//3).
    # 50k chars was 16k tok and never trimmed — test bug, not a trim crash.
    skill_blob = "y" * 120_000
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
        "single_turn_orig_tokens": single_meta.get("original_tokens_estimate"),
        "single_turn_cap": single_meta.get("input_cap_tokens"),
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

    try:
        from inference_queue import get_inference_queue

        get_inference_queue()
    except Exception as exc:
        print(f"inference queue init skipped: {exc}", file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), SovereignProxyHandler)
    print(f"Phronesis MoE gateway listening on http://{args.host}:{args.port}")
    print("Endpoints: /health /v1/queue /v1/queue/{id} /v1/models /v1/chat/completions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
