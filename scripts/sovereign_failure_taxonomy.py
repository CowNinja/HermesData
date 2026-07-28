#!/usr/bin/env python3
"""
sovereign_failure_taxonomy.py ? Shared failure classes for Phronesis router/agent.

Used by model_management_agent, docs, and (optionally) proxy diagnostics.
Keep thin: classify ? retry policy hints. No network I/O.

Research basis (2026-07-18):
- LLM gateway resilience: retry ? fallback ? circuit-break (per provider+model)
- FIFO 503 = capacity, not crash (local-model-management FIFO load testing)
- reasoning_content empty-content false negative (L07 2026-07-18)
- LiteLLM cooldown/connection pitfalls ? avoid retry storms
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Canonical classes
TRANSIENT = "transient"  # timeout, connection reset, CUDA busy ? retry with backoff
PERMANENT = "permanent"  # missing GGUF, bad config, 4xx auth ? do not retry same path
CAPACITY = "capacity"  # FIFO full, VRAM pressure, rate limit ? wait / degrade
DEGRADED = "degraded"  # smoke weak, stale bench, fallback tier ? operate with warning
POLICY = "policy"  # fail_closed, fleet locked, fleet OFF ? intentional block
UNKNOWN = "unknown"

CLASS_HINTS: Dict[str, Dict[str, Any]] = {
    TRANSIENT: {
        "retry": True,
        "backoff": "exp_jitter",
        "max_attempts": 3,
        "escalate_after": True,
    },
    PERMANENT: {
        "retry": False,
        "backoff": None,
        "max_attempts": 1,
        "escalate_after": False,
        "operator": True,
    },
    CAPACITY: {
        "retry": True,
        "backoff": "fixed_wait",
        "max_attempts": 2,
        "retry_after_sec_default": 15,
        "escalate_after": False,
    },
    DEGRADED: {
        "retry": False,
        "backoff": None,
        "max_attempts": 1,
        "operator": True,
        "note": "continue serving; schedule bench/heal",
    },
    POLICY: {
        "retry": False,
        "backoff": None,
        "max_attempts": 1,
        "note": "intentional; document rationale",
    },
    UNKNOWN: {
        "retry": True,
        "backoff": "exp_jitter",
        "max_attempts": 2,
        "operator": True,
    },
}

# Map agent issue codes ? class
ISSUE_CODE_CLASS = {
    "L01": PERMANENT,  # missing file
    "L02": TRANSIENT,  # wrong model loaded ? restart often fixes
    "L03": TRANSIENT,  # 8090 down
    "L04": PERMANENT,  # split GGUF manual
    "L05": DEGRADED,  # no bench
    "L06": DEGRADED,  # stale bench
    "L07": TRANSIENT,  # smoke fail (may be busy/thinking)
    "L08": DEGRADED,  # low scores
    "L09": DEGRADED,  # drift
    "S01": TRANSIENT,  # proxy down
    "S02": TRANSIENT,  # gateway down
    "S03": TRANSIENT,  # stack incomplete
    "C00": POLICY,  # fleet OFF
    "C01": DEGRADED,  # cloud degraded
    "C02": PERMANENT,  # missing keys
    "P01": POLICY,  # no paid fallbacks configured (often intentional)
    "F01": POLICY,  # promote suggest
    "F02": DEGRADED,
    "F03": DEGRADED,
}


def classify_issue_code(code: Optional[str]) -> str:
    if not code:
        return UNKNOWN
    return ISSUE_CODE_CLASS.get(str(code).upper(), UNKNOWN)


def classify_exception_message(msg: str) -> str:
    m = (msg or "").lower()
    # Permanent: malformed requests / template grammar ? must NOT retry as 503.
    if any(
        x in m
        for x in (
            "unable to generate parser",
            "callexpression",
            "chat template",
            "template parser",
            "http 400",
            "status 400",
            "bad request",
            "invalid_request",
            "json schema",
            "grammar",
        )
    ):
        return PERMANENT
    if any(x in m for x in ("fifo", "at capacity", "retry_after", "429", "rate limit")):
        return CAPACITY
    if any(x in m for x in ("timeout", "timed out", "connection reset", "10054", "refused", "temporarily", "10061")):
        return TRANSIENT
    if any(x in m for x in ("not found", "missing", "no such file", "401", "403", "invalid model", "http 401", "http 403")):
        return PERMANENT
    if "empty_content" in m or "reasoning" in m:
        return TRANSIENT
    # Bare 5xx strings are capacity/transient infrastructure.
    if any(x in m for x in ("http 502", "http 503", "http 504", "service unavailable")):
        return TRANSIENT
    return UNKNOWN


def classify_http_status(status: Optional[int], msg: str = "") -> str:
    """Classify by upstream HTTP status, with message fallback."""
    try:
        code = int(status) if status is not None else None
    except (TypeError, ValueError):
        code = None
    if code is not None:
        if code == 429:
            return CAPACITY
        if 400 <= code < 500:
            # 408 Request Timeout is the only common 4xx that is transient.
            if code == 408:
                return TRANSIENT
            return PERMANENT
        if code in (502, 503, 504):
            # Prefer message if it looks like a disguised permanent error.
            msg_cls = classify_exception_message(msg) if msg else UNKNOWN
            if msg_cls == PERMANENT:
                return PERMANENT
            return TRANSIENT
        if code >= 500:
            return TRANSIENT
    return classify_exception_message(msg) if msg else UNKNOWN


def http_status_for_failure_class(cls: str, *, default_transient: int = 503) -> int:
    """Map failure class ? client-facing HTTP status.

    Critical: PERMANENT must return 4xx so OpenAI SDKs and Hermes do not
    treat the error as retriable infrastructure (503).
    """
    if cls == PERMANENT:
        return 400
    if cls == CAPACITY:
        return 429
    if cls == POLICY:
        return 403
    if cls == DEGRADED:
        return 503
    return int(default_transient)


def openai_error_type_for_class(cls: str) -> str:
    if cls == PERMANENT:
        return "invalid_request_error"
    if cls == CAPACITY:
        return "rate_limit_error"
    if cls == POLICY:
        return "permission_error"
    return "server_error"


def classify_dispatch_failure(
    msg: str,
    *,
    http_status: Optional[int] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full classification for proxy dispatch_fail / escalation paths."""
    prov = provenance or {}
    combined = " ".join(
        str(x)
        for x in (
            msg,
            prov.get("error"),
            prov.get("local_fail_reason"),
            prov.get("grammar_error"),
        )
        if x
    )
    # Explicit status from upstream if present in message text.
    if http_status is None:
        import re

        m = re.search(r"HTTP\s+(\d{3})", combined, re.I)
        if m:
            try:
                http_status = int(m.group(1))
            except ValueError:
                http_status = None
    cls = classify_http_status(http_status, combined)
    return {
        "failure_class": cls,
        "failure_hint": CLASS_HINTS.get(cls, CLASS_HINTS[UNKNOWN]),
        "http_status": http_status_for_failure_class(cls),
        "error_type": openai_error_type_for_class(cls),
        "retryable": bool(CLASS_HINTS.get(cls, CLASS_HINTS[UNKNOWN]).get("retry")),
        "upstream_http_status": http_status,
    }


def annotate_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Return shallow copy with failure_class + retry hint."""
    out = dict(issue)
    code = out.get("code")
    cls = classify_issue_code(str(code) if code else None)
    if cls == UNKNOWN and out.get("message"):
        cls = classify_exception_message(str(out.get("message")))
    out["failure_class"] = cls
    out["failure_hint"] = CLASS_HINTS.get(cls, CLASS_HINTS[UNKNOWN])
    out["client_http_status"] = http_status_for_failure_class(cls)
    out["retryable"] = bool(CLASS_HINTS.get(cls, CLASS_HINTS[UNKNOWN]).get("retry"))
    return out


def annotate_issues(issues: list) -> list:
    return [annotate_issue(i) if isinstance(i, dict) else i for i in (issues or [])]
