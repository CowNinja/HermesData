#!/usr/bin/env python3
"""E2E: sovereign proxy accepts Grok-era tool history after flatten."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8091/v1/chat/completions"


def main() -> int:
    msgs = [
        {"role": "system", "content": "You are Hermes. Reply in one short sentence."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "dir"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "name": "terminal", "content": "file.txt"},
        {"role": "user", "content": "What files did you see? One word answer."},
    ]
    body = json.dumps(
        {
            "model": "phronesis-sovereign-auto",
            "messages": msgs,
            "max_tokens": 64,
            "temperature": 0.3,
        }
    ).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            print(f"STATUS {resp.status}")
            print(f"CHOICE {content[:300]!r}")
            return 0 if content.strip() else 1
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:500]}")
        return 1
    except Exception as exc:
        print(f"FAIL {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())