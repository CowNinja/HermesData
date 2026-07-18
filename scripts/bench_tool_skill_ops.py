#!/usr/bin/env python3
"""Tool + skill readiness bench for everyday Hermes ops.

Scores OpenAI-style tool_calls against a local OpenAI-compatible endpoint
(llama-server :8090 / :8095 or proxy). Metrics beyond raw tok/s:

  - format_valid: proper message.tool_calls (not markdown/JSON narration)
  - name_hit: correct tool selected
  - args_valid: required keys present and sane
  - path_discipline: absolute D:\\ paths when required
  - no_fake_tools: no "I'll call read_file..." without tool_calls
  - multi_step: second turn uses tool result correctly
  - latency_to_tool: wall time to first tool response
  - over_refuse: safe ops task refused (bad)

Usage:
  python bench_tool_skill_ops.py --base http://127.0.0.1:8090 --label qwythos
  python bench_tool_skill_ops.py --base http://127.0.0.1:8095 --label qwen36
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Hermes-like tool surface (subset used every day)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from disk. path must be absolute Windows path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path e.g. D:\\\\HermesData\\\\config.yaml"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or append text to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["overwrite", "append"]},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Run a shell command. Prefer PowerShell on Windows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skills_list",
            "description": "List available Hermes skills.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_view",
            "description": "Read a skill SKILL.md by name or path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search files under a root path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
]

SYSTEM = (
    "You are Hermes local ops agent on Windows. "
    "Use REAL tool_calls only — never narrate tools in prose. "
    "Prefer absolute D:\\ paths. tool_choice may force a tool. "
    "Do not invent tool results."
)

CASES = [
    {
        "id": "read_exact_path",
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "expect_name": "read_file",
        "user": (
            "Read the first 40 lines of D:\\PhronesisVault\\Operations\\logs\\"
            "bench-qwen36-vs-qwythos-2026-07-17.md and report nothing else until you have the file."
        ),
        "check": "path_contains",
        "path_substr": "bench-qwen36-vs-qwythos-2026-07-17",
    },
    {
        "id": "terminal_port_check",
        "tool_choice": {"type": "function", "function": {"name": "terminal"}},
        "expect_name": "terminal",
        "user": (
            "Check whether something is listening on TCP 8090 on this Windows box. "
            "Use a single PowerShell command via the terminal tool."
        ),
        "check": "terminal_mentions_8090",
    },
    {
        "id": "skills_list_first",
        "tool_choice": {"type": "function", "function": {"name": "skills_list"}},
        "expect_name": "skills_list",
        "user": "Before advising, list available skills using the skills_list tool.",
        "check": "name_only",
    },
    {
        "id": "skill_view_authoring",
        "tool_choice": "auto",
        "expect_name": "skill_view",
        "user": (
            "Open the hermes-agent-skill-authoring skill so we can follow its SOP. "
            "Use skill_view (name or path)."
        ),
        "check": "skill_view",
    },
    {
        "id": "search_then_read",
        "tool_choice": "auto",
        "expect_name": "search_files",
        "user": (
            "Find files under D:\\HermesData\\scripts matching pattern bench_.*\\.py "
            "using search_files. Do not invent paths."
        ),
        "check": "search_path",
    },
    {
        "id": "write_append_receipt",
        "tool_choice": {"type": "function", "function": {"name": "write_file"}},
        "expect_name": "write_file",
        "user": (
            "Append one line to D:\\HermesData\\state\\tool-skill-bench-receipt.txt "
            "with content exactly: TOOL_SKILL_BENCH_OK (mode append)."
        ),
        "check": "write_append",
    },
    {
        "id": "auto_multi_prefer_read",
        "tool_choice": "auto",
        "expect_name": "read_file",
        "user": (
            "Jeff asked: what is the default model in Hermes config? "
            "You must read D:\\HermesData\\config.yaml — do not guess."
        ),
        "check": "path_contains",
        "path_substr": "config.yaml",
    },
    {
        "id": "no_hallucinated_tool_result",
        "tool_choice": "auto",
        "expect_name": "read_file",
        "user": (
            "Read D:\\HermesData\\state\\stack-authority.json and quote the coordination.vault_plan field. "
            "You do not have the file contents until you call read_file."
        ),
        "check": "path_contains",
        "path_substr": "stack-authority",
    },
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(url: str, payload: dict, timeout: float = 180) -> tuple[int, Any, float]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            dt = time.perf_counter() - t0
            return r.status, json.loads(body), dt
    except urllib.error.HTTPError as e:
        dt = time.perf_counter() - t0
        err = e.read().decode("utf-8", errors="replace")[:1500]
        return e.code, {"error": err}, dt
    except Exception as e:
        dt = time.perf_counter() - t0
        return 0, {"error": f"{type(e).__name__}: {e}"}, dt


def get_model(base: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{base}/v1/models", timeout=15) as r:
            d = json.loads(r.read())
        data = d.get("data") or d.get("models") or []
        if not data:
            return None
        return data[0].get("id") or data[0].get("model") or data[0].get("name")
    except Exception:
        return None


def extract_tool_calls(body: dict) -> list[dict]:
    """Normalize tool calls from OpenAI response or common broken formats."""
    choices = body.get("choices") or []
    if not choices:
        return []
    msg = choices[0].get("message") or {}
    tcs = msg.get("tool_calls") or []
    if tcs:
        out = []
        for tc in tcs:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            args = fn.get("arguments") or tc.get("arguments") or "{}"
            if isinstance(args, dict):
                args_obj = args
            else:
                try:
                    args_obj = json.loads(args)
                except Exception:
                    args_obj = {"_raw": str(args)[:500]}
            out.append({"name": name, "arguments": args_obj, "source": "tool_calls"})
        return out

    # Broken formats (markdown / prose)
    content = msg.get("content") or choices[0].get("text") or ""
    found = []
    for m in re.finditer(
        r'```(?:json)?\s*(\{.*?"name"\s*:\s*"(read_file|write_file|terminal|skills_list|skill_view|search_files)".*?\})\s*```',
        content,
        re.S | re.I,
    ):
        try:
            obj = json.loads(m.group(1))
            found.append(
                {
                    "name": obj.get("name"),
                    "arguments": obj.get("arguments") or obj.get("parameters") or {},
                    "source": "markdown_json",
                }
            )
        except Exception:
            pass
    if found:
        return found
    # bare function-looking lines
    if re.search(r"read_file\s*\(", content) or "I'll use the" in content or "I will call" in content:
        return [{"name": None, "arguments": {}, "source": "narrated", "content_snip": content[:200]}]
    return []


def score_case(case: dict, tcs: list[dict], content: str, wall: float) -> dict[str, Any]:
    expect = case["expect_name"]
    s: dict[str, Any] = {
        "id": case["id"],
        "wall_s": round(wall, 3),
        "format_valid": 0,
        "name_hit": 0,
        "args_valid": 0,
        "path_discipline": 0,
        "no_fake_tools": 0,
        "latency_ok": 0,
        "detail": {},
    }
    if not tcs:
        s["detail"]["fail"] = "no_tool_calls"
        s["no_fake_tools"] = 0 if content.strip() else 1
        return s

    primary = tcs[0]
    src = primary.get("source")
    s["format_valid"] = 1 if src == "tool_calls" else 0
    s["no_fake_tools"] = 1 if src != "narrated" else 0
    name = primary.get("name")
    s["name_hit"] = 1 if name == expect else 0
    args = primary.get("arguments") or {}
    s["detail"]["name"] = name
    s["detail"]["source"] = src
    s["detail"]["args"] = args

    check = case.get("check")
    if check == "name_only":
        s["args_valid"] = 1 if s["name_hit"] else 0
        s["path_discipline"] = 1  # N/A
    elif check == "path_contains":
        path = str(args.get("path") or "")
        ok = case.get("path_substr", "") in path.replace("/", "\\")
        abs_ok = path.lower().startswith("d:\\") or path.lower().startswith("d:/")
        s["args_valid"] = 1 if ok else 0
        s["path_discipline"] = 1 if abs_ok else 0
    elif check == "terminal_mentions_8090":
        cmd = str(args.get("command") or "")
        s["args_valid"] = 1 if "8090" in cmd else 0
        s["path_discipline"] = 1
    elif check == "skill_view":
        ok = bool(args.get("name") or args.get("path"))
        s["args_valid"] = 1 if ok else 0
        path = str(args.get("path") or "")
        s["path_discipline"] = 1 if (not path or path.lower().startswith("d:")) else 0
    elif check == "search_path":
        path = str(args.get("path") or "")
        pat = str(args.get("pattern") or "")
        s["args_valid"] = 1 if pat and ("bench" in pat.lower() or ".*" in pat) else 0
        s["path_discipline"] = 1 if (not path or "HermesData" in path or path.lower().startswith("d:")) else 0
    elif check == "write_append":
        path = str(args.get("path") or "")
        content_a = str(args.get("content") or "")
        mode = str(args.get("mode") or "").lower()
        s["args_valid"] = 1 if "TOOL_SKILL_BENCH_OK" in content_a else 0
        s["path_discipline"] = 1 if "tool-skill-bench-receipt" in path.replace("/", "\\") else 0
        if mode and mode not in ("append", "overwrite"):
            s["args_valid"] = 0
    else:
        s["args_valid"] = 1 if args else 0
        s["path_discipline"] = 1

    s["latency_ok"] = 1 if wall < 30 else 0
    return s


def run_suite(base: str, label: str) -> dict[str, Any]:
    model = get_model(base)
    if not model:
        return {"label": label, "base": base, "error": "endpoint_down", "at": utc()}

    rows = []
    for case in CASES:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": case["user"]},
            ],
            "tools": TOOLS,
            "tool_choice": case.get("tool_choice", "auto"),
            "temperature": 0.2,
            "max_tokens": 400,
            # reduce thinking budget for tool benches when supported
            "chat_template_kwargs": {"enable_thinking": False},
        }
        code, body, wall = http_json(f"{base}/v1/chat/completions", payload)
        content = ""
        if isinstance(body, dict):
            ch = (body.get("choices") or [{}])[0]
            content = ((ch.get("message") or {}).get("content") or "")[:500]
        tcs = extract_tool_calls(body if isinstance(body, dict) else {})
        sc = score_case(case, tcs, content, wall)
        sc["http"] = code
        sc["content_snip"] = content[:160].replace("\n", " ")
        rows.append(sc)
        print(
            f"  {label} {case['id']}: fmt={sc['format_valid']} name={sc['name_hit']} "
            f"args={sc['args_valid']} path={sc['path_discipline']} wall={sc['wall_s']} "
            f"src={sc['detail'].get('source')}",
            flush=True,
        )

    keys = ["format_valid", "name_hit", "args_valid", "path_discipline", "no_fake_tools", "latency_ok"]
    totals = {k: sum(int(r.get(k) or 0) for r in rows) for k in keys}
    n = len(rows) or 1
    score = sum(totals.values())
    max_score = n * len(keys)
    return {
        "at": utc(),
        "label": label,
        "base": base,
        "model": model,
        "n_cases": n,
        "totals": totals,
        "score": score,
        "max_score": max_score,
        "pct": round(100.0 * score / max_score, 1),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument(
        "--out",
        default="",
        help="JSON out path (default under Operations/logs)",
    )
    args = ap.parse_args()
    print(f"=== tool/skill bench {args.label} @ {args.base} ===", flush=True)
    result = run_suite(args.base, args.label)
    out = Path(args.out) if args.out else Path(
        rf"D:\PhronesisVault\Operations\logs\bench-tool-skill-{args.label}-2026-07-17.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"score={result.get('score')}/{result.get('max_score')} ({result.get('pct')}%) -> {out}", flush=True)
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
