#!/usr/bin/env python3
"""
sovereign_failure_taxonomy.py — Shared failure classes for Phronesis router/agent.

Used by model_management_agent, docs, and (optionally) proxy diagnostics.
Keep thin: classify → retry policy hints. No network I/O.

Research basis (2026-07-18):
- LLM gateway resilience: retry → fallback → circuit-break (per provider+model)
- FIFO 503 = capacity, not crash (local-model-management FIFO load testing)
- reasoning_content empty-content false negative (L07 2026-07-18)
- LiteLLM cooldown/connection pitfalls — avoid retry storms
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Canonical classes
TRANSIENT = "transient"  # timeout, connection reset, CUDA busy — retry with backoff
PERMANENT = "permanent"  # missing GGUF, bad config, 4xx auth — do not retry same path
CAPACITY = "capacity"  # FIFO full, VRAM pressure, rate limit — wait / degrade
DEGRADED = "degraded"  # smoke weak, stale bench, fallback tier — operate with warning
POLICY = "policy"  # fail_closed, fleet locked, fleet OFF — intentional block
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

# Map agent issue codes → class
ISSUE_CODE_CLASS = {
    "L01": PERMANENT,  # missing file
    "L02": TRANSIENT,  # wrong model loaded — restart often fixes
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
    if any(x in m for x in ("fifo", "at capacity", "retry_after", "429", "rate limit")):
        return CAPACITY
    if any(x in m for x in ("timeout", "timed out", "connection reset", "10054", "refused", "temporarily")):
        return TRANSIENT
    if any(x in m for x in ("not found", "missing", "no such file", "401", "403", "invalid model")):
        return PERMANENT
    if "empty_content" in m or "reasoning" in m:
        return TRANSIENT
    return UNKNOWN


def annotate_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Return shallow copy with failure_class + retry hint."""
    out = dict(issue)
    code = out.get("code")
    cls = classify_issue_code(str(code) if code else None)
    if cls == UNKNOWN and out.get("message"):
        cls = classify_exception_message(str(out.get("message")))
    out["failure_class"] = cls
    out["failure_hint"] = CLASS_HINTS.get(cls, CLASS_HINTS[UNKNOWN])
    return out


def annotate_issues(issues: list) -> list:
    return [annotate_issue(i) if isinstance(i, dict) else i for i in (issues or [])]
