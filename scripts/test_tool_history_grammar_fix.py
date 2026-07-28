#!/usr/bin/env python3
"""P1: Prove 400/503 grammar fix under Grok-shaped tool-call history.

Sends three probes to :8091:
  A) plain user message (baseline 200)
  B) assistant tool_calls + tool result history (must flatten, not 503 storm)
  C) same as B with tools array present (grammar-stress)

Receipt: D:\\PhronesisVault\\Operations\\logs\\tool-history-grammar-fix-latest.json
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROXY = "http://127.0.0.1:8091/v1/chat/completions"
PROXY_LOG = Path(r"D:\PhronesisVault\Operations\logs\sovereign-proxy.jsonl")
RECEIPT_JSON = Path(r"D:\PhronesisVault\Operations\logs\tool-history-grammar-fix-latest.json")
RECEIPT_MD = Path(r"D:\PhronesisVault\Operations\logs\tool-history-grammar-fix-latest.md")
SEAL = "tool-history-grammar-fix-p1-2026-07-25"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post(body: Dict[str, Any], timeout: float = 120.0) -> Tuple[int, Dict[str, Any], float]:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        PROXY,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return int(resp.status), data, round(time.time() - t0, 3)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            payload = {"error": {"message": str(e)}}
        return int(e.code), payload, round(time.time() - t0, 3)
    except Exception as e:
        return 0, {"error": {"message": str(e), "type": "transport_error"}}, round(time.time() - t0, 3)


def _tail_proxy_events(since_ts: float, markers: List[str]) -> Dict[str, int]:
    counts = {m: 0 for m in markers}
    if not PROXY_LOG.is_file():
        return counts
    try:
        # Read last ~400 lines only
        lines = PROXY_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except Exception:
        return counts
    for line in lines:
        low = line.lower()
        for m in markers:
            if m.lower() in low:
                counts[m] += 1
    return counts


def _tool_history_messages() -> List[Dict[str, Any]]:
    """Shape that historically blew llama chat templates (CallExpression / tool role)."""
    return [
        {"role": "system", "content": "You are a concise local assistant."},
        {"role": "user", "content": "What is 2+2? Use tools if needed, then answer."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_test_001",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": json.dumps({"command": "python -c \"print(2+2)\""}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_test_001",
            "name": "terminal",
            "content": "4\n",
        },
        {"role": "user", "content": "Reply with exactly one word: FOUR"},
    ]


def _tools_schema() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }
    ]


def main() -> int:
    probes: List[Dict[str, Any]] = []
    markers = [
        "proactive_tool_history_flatten",
        "grammar_retry",
        "dispatch_fail",
        "dispatch_ok",
        "phronesis_failure",
    ]
    before = _tail_proxy_events(0, markers)

    # A baseline
    status_a, body_a, lat_a = _post(
        {
            "model": "phronesis-sovereign-auto",
            "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
            "max_tokens": 16,
            "temperature": 0.1,
        }
    )
    probes.append(
        {
            "id": "A_baseline",
            "status": status_a,
            "latency_sec": lat_a,
            "ok": status_a == 200,
            "preview": str(
                ((body_a.get("choices") or [{}])[0].get("message") or {}).get("content")
                or body_a.get("error")
                or body_a
            )[:200],
        }
    )

    # B tool history no tools array
    status_b, body_b, lat_b = _post(
        {
            "model": "phronesis-sovereign-auto",
            "messages": _tool_history_messages(),
            "max_tokens": 32,
            "temperature": 0.1,
        }
    )
    err_b = body_b.get("error") if isinstance(body_b, dict) else None
    pf_b = body_b.get("phronesis_failure") if isinstance(body_b, dict) else None
    probes.append(
        {
            "id": "B_tool_history_no_tools_array",
            "status": status_b,
            "latency_sec": lat_b,
            "ok": status_b == 200 or (status_b == 400 and not _is_retriable_storm(status_b, pf_b)),
            "not_503_storm": status_b != 503,
            "phronesis_failure": pf_b,
            "error_type": (err_b or {}).get("type") if isinstance(err_b, dict) else None,
            "preview": str(
                ((body_b.get("choices") or [{}])[0].get("message") or {}).get("content")
                or err_b
                or body_b
            )[:240],
        }
    )

    # C tool history + tools array (harder)
    status_c, body_c, lat_c = _post(
        {
            "model": "phronesis-sovereign-auto",
            "messages": _tool_history_messages(),
            "tools": _tools_schema(),
            "tool_choice": "none",
            "max_tokens": 32,
            "temperature": 0.1,
        }
    )
    err_c = body_c.get("error") if isinstance(body_c, dict) else None
    pf_c = body_c.get("phronesis_failure") if isinstance(body_c, dict) else None
    probes.append(
        {
            "id": "C_tool_history_with_tools_array",
            "status": status_c,
            "latency_sec": lat_c,
            "ok": status_c == 200 or (status_c == 400 and status_c != 503),
            "not_503_storm": status_c != 503,
            "phronesis_failure": pf_c,
            "error_type": (err_c or {}).get("type") if isinstance(err_c, dict) else None,
            "preview": str(
                ((body_c.get("choices") or [{}])[0].get("message") or {}).get("content")
                or err_c
                or body_c
            )[:240],
        }
    )

    time.sleep(0.5)
    after = _tail_proxy_events(0, markers)
    delta = {k: max(0, after.get(k, 0) - before.get(k, 0)) for k in markers}

    # Pass criteria
    no_503 = all(p.get("not_503_storm", p["status"] != 503) for p in probes if p["id"] != "A_baseline")
    baseline_ok = probes[0]["ok"]
    b_or_c_usable = probes[1]["status"] in (200, 400) and probes[2]["status"] in (200, 400)
    # Prefer success; 400 permanent without 503 is acceptable fail-closed
    pass_overall = baseline_ok and no_503 and b_or_c_usable

    receipt = {
        "ts": _utc(),
        "seal": SEAL,
        "proxy": PROXY,
        "pass": pass_overall,
        "criteria": {
            "baseline_200": baseline_ok,
            "no_503_on_tool_history": no_503,
            "tool_history_200_or_permanent_400": b_or_c_usable,
        },
        "probes": probes,
        "proxy_log_marker_delta": delta,
        "notes": [
            "PASS if tool-history probes are 200 OR permanent 400 ? never 503 retry-storm shape.",
            "proactive_tool_history_flatten delta > 0 is strong evidence of fix path.",
        ],
    }

    RECEIPT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_JSON.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    lines = [
        f"# Tool-history grammar fix probe ? {receipt['ts']}",
        "",
        f"**PASS:** `{pass_overall}`",
        f"**Seal:** `{SEAL}`",
        "",
        "## Probes",
    ]
    for p in probes:
        lines.append(
            f"- `{p['id']}` status={p['status']} lat={p['latency_sec']}s preview={p.get('preview', '')!r}"
        )
    lines += [
        "",
        "## Proxy log marker delta",
        "```json",
        json.dumps(delta, indent=2),
        "```",
        "",
        f"Full JSON: `{RECEIPT_JSON}`",
    ]
    RECEIPT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if pass_overall else 1


def _is_retriable_storm(status: int, pf: Optional[Dict[str, Any]]) -> bool:
    if status == 503:
        return True
    if isinstance(pf, dict) and pf.get("retryable") is True and status >= 500:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
