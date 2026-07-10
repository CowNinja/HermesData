#!/usr/bin/env python3
"""Unit tests for proactive routing classification."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from proactive_routing_policy import (  # noqa: E402
    ROUTING_AUGMENT_LOCAL,
    ROUTING_LOCAL_FIRST,
    ROUTING_LOCAL_ONLY,
    ROUTING_OFFLOAD_COMPUTE,
    classify_proactive_routing,
    contains_sensitive_content,
    sanitize_for_fleet,
)


def test_roleplay_stays_local() -> None:
    result = classify_proactive_routing(
        "Continue the scene.",
        {"platform": "discord-roleplay", "task_type": "roleplay"},
        [{"role": "user", "content": "Continue the scene."}],
    )
    assert result["mode"] == ROUTING_LOCAL_ONLY
    assert not result["eligible"]


def test_tools_stay_local() -> None:
    result = classify_proactive_routing(
        "read_file D:\\HermesData\\config.yaml",
        {"task_type": "code"},
        [{"role": "user", "content": "read_file D:\\HermesData\\config.yaml"}],
        {"tools": [{"type": "function", "function": {"name": "read_file"}}]},
    )
    assert result["mode"] == ROUTING_LOCAL_ONLY


def test_pii_stays_local() -> None:
    result = classify_proactive_routing(
        "Email me at alice@example.com",
        {"task_type": "general"},
        [{"role": "user", "content": "Email me at alice@example.com"}],
    )
    assert result["mode"] == ROUTING_LOCAL_ONLY
    assert "email_pii" in result["reasons"]


def test_public_research_offloads() -> None:
    result = classify_proactive_routing(
        "Summarize the latest trends in open source LLM routers.",
        {"task_type": "research"},
        [{"role": "user", "content": "Summarize the latest trends in open source LLM routers."}],
    )
    assert result["mode"] == ROUTING_OFFLOAD_COMPUTE
    assert result["eligible"]
    assert "summarize" in " ".join(result["reasons"]).lower() or "task_type:research" in result["reasons"]


def test_header_force_offload() -> None:
    result = classify_proactive_routing(
        "Hello",
        {"task_type": "general"},
        [{"role": "user", "content": "Hello"}],
        headers={"X-Phronesis-Routing": "offload"},
    )
    assert result["mode"] == ROUTING_OFFLOAD_COMPUTE


def test_sanitize_redacts_paths() -> None:
    raw = "Check D:\\PhronesisVault\\Operations\\logs\\foo.json"
    clean = sanitize_for_fleet(raw)
    assert "PhronesisVault" not in clean
    assert "[LOCAL_PATH_REDACTED]" in clean


def test_explicit_content_local() -> None:
    sensitive, reason = contains_sensitive_content("OOC: portrait in bedroom scene")
    assert sensitive
    assert reason.startswith("explicit:")


def test_default_local_first() -> None:
    result = classify_proactive_routing(
        "Thanks!",
        {"task_type": "general"},
        [{"role": "user", "content": "Thanks!"}],
    )
    assert result["mode"] in (ROUTING_LOCAL_FIRST, ROUTING_AUGMENT_LOCAL, ROUTING_LOCAL_ONLY)


def test_ambiguous_stays_local() -> None:
    result = classify_proactive_routing(
        "Can you help with this?",
        {"task_type": "general"},
        [{"role": "user", "content": "Can you help with this?"}],
    )
    assert result["mode"] == ROUTING_LOCAL_FIRST
    assert not result["eligible"]


def test_private_path_blocks_offload() -> None:
    result = classify_proactive_routing(
        "Summarize D:\\PhronesisVault\\Operations\\logs\\agent.log",
        {"task_type": "research"},
        [{"role": "user", "content": "Summarize D:\\PhronesisVault\\Operations\\logs\\agent.log"}],
    )
    assert result["mode"] == ROUTING_LOCAL_ONLY
    assert not result["eligible"]


def test_explicit_stays_local() -> None:
    result = classify_proactive_routing(
        "Continue the explicit bedroom scene",
        {"task_type": "general"},
        [{"role": "user", "content": "Continue the explicit bedroom scene"}],
    )
    assert result["mode"] == ROUTING_LOCAL_ONLY


def main() -> int:
    tests = [
        test_roleplay_stays_local,
        test_tools_stay_local,
        test_pii_stays_local,
        test_public_research_offloads,
        test_header_force_offload,
        test_sanitize_redacts_paths,
        test_explicit_content_local,
        test_default_local_first,
        test_ambiguous_stays_local,
        test_private_path_blocks_offload,
        test_explicit_stays_local,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())