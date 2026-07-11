#!/usr/bin/env python3
"""Smoke test: Grok tool history flattens for llama-server dispatch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sovereign_openai_proxy import _flatten_tool_history_for_llama  # noqa: E402


def test_flattens_tool_turns() -> None:
    raw = [
        {"role": "system", "content": "You are Hermes."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "ls"}'},
                }
            ],
            "reasoning_content": "thinking...",
        },
        {"role": "tool", "tool_call_id": "call_abc", "name": "terminal", "content": "file.txt"},
        {"role": "user", "content": "thanks"},
    ]
    flat = _flatten_tool_history_for_llama(raw)
    assert all("tool_calls" not in m for m in flat)
    assert all(m.get("role") != "tool" for m in flat)
    roles = [m["role"] for m in flat]
    assert roles == ["system", "assistant", "user", "user"]
    assert "Called terminal" in flat[1]["content"]
    assert "Tool result" in flat[2]["content"]
    print("flatten_ok", json.dumps(flat, indent=2)[:400])


if __name__ == "__main__":
    test_flattens_tool_turns()
    print("PASSED")