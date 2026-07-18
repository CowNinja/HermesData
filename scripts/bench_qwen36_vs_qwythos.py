#!/usr/bin/env python3
"""Timed A/B: live Qwythos :8090 vs Qwen3.6-35B-A3B abliterated :8095.

Reports TTFT, tok/s, tokens, and short sample tails. $0 cloud.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENDPOINTS = {
    "qwythos_9b_q6": "http://127.0.0.1:8090",
    "qwen36_35b_a3b_q4ks": "http://127.0.0.1:8095",
}

PROMPTS = [
    {
        "id": "latency_pong",
        "max_tokens": 16,
        "content": "Reply with only the single word: pong",
    },
    {
        "id": "ops_runbook",
        "max_tokens": 256,
        "content": (
            "Write a concise Windows ops runbook (bullet steps) for restarting "
            "a local llama-server on port 8090 without dropping a Discord gateway "
            "on 8642. Include health-check URLs."
        ),
    },
    {
        "id": "code_lru",
        "max_tokens": 400,
        "content": (
            "Write a complete Python class: thread-safe LRU cache with TTL. "
            "Include type hints and a short docstring. No markdown fences."
        ),
    },
    {
        "id": "synthesis_local_first",
        "max_tokens": 350,
        "content": (
            "In under 350 words, compare local-first sovereign inference "
            "(llama.cpp on RTX 3060) vs cloud APIs for a personal AI stack. "
            "Cover latency, privacy, cost, and failure modes."
        ),
    },
    {
        "id": "agent_debug",
        "max_tokens": 280,
        "content": (
            "Error log excerpt:\n"
            "llama-server: CUDA OOM allocating KV cache for n_parallel=4 ctx=65536\n"
            "proxy 8091: GREEN but TTFT > 30s\n"
            "List 5 ranked fixes with one-line rationale each. Most impactful first."
        ),
    },
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(url: str, payload: dict | None = None, timeout: float = 600) -> tuple[int, Any, float]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            dt = time.perf_counter() - t0
            try:
                return r.status, json.loads(body), dt
            except json.JSONDecodeError:
                return r.status, {"raw": body[:2000]}, dt
    except urllib.error.HTTPError as e:
        dt = time.perf_counter() - t0
        err = e.read().decode("utf-8", errors="replace")[:1500]
        return e.code, {"error": err}, dt
    except Exception as e:
        dt = time.perf_counter() - t0
        return 0, {"error": f"{type(e).__name__}: {e}"}, dt


def list_model(base: str) -> str | None:
    code, body, _ = http_json(f"{base}/v1/models", None, timeout=10)
    if code != 200 or not isinstance(body, dict):
        return None
    data = body.get("data") or body.get("models") or []
    if not data:
        return None
    first = data[0]
    return first.get("id") or first.get("model") or first.get("name")


def chat_once(base: str, model: str, prompt: dict) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt["content"]}],
        "max_tokens": prompt["max_tokens"],
        "temperature": 0.7,
        "stream": False,
    }
    # Wall clock ≈ total latency; without streaming TTFT ≈ total for small outs
    code, body, wall = http_json(f"{base}/v1/chat/completions", payload, timeout=900)
    out: dict[str, Any] = {
        "http": code,
        "wall_s": round(wall, 3),
        "ok": code == 200,
    }
    if not isinstance(body, dict):
        out["error"] = "bad_body"
        return out
    if "error" in body and code != 200:
        out["error"] = body.get("error")
        return out
    choices = body.get("choices") or []
    text = ""
    if choices:
        msg = choices[0].get("message") or {}
        text = msg.get("content") or choices[0].get("text") or ""
    usage = body.get("usage") or {}
    completion_tokens = int(usage.get("completion_tokens") or 0)
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    # Prefer server timings if present
    timings = body.get("timings") or {}
    pred_n = timings.get("predicted_n") or completion_tokens
    pred_ms = timings.get("predicted_ms")
    prompt_ms = timings.get("prompt_ms")
    if pred_ms and pred_n:
        tok_s = float(pred_n) / (float(pred_ms) / 1000.0)
        ttft_ms = float(prompt_ms) if prompt_ms is not None else None
    else:
        tok_s = (completion_tokens / wall) if wall > 0 and completion_tokens else None
        ttft_ms = wall * 1000.0  # non-stream upper bound
    out.update(
        {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tok_s": round(tok_s, 2) if tok_s is not None else None,
            "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
            "timings": timings,
            "sample": (text or "")[:280].replace("\n", " "),
        }
    )
    return out


def main() -> int:
    runs = 2  # after warmup
    results: dict[str, Any] = {"at": utc(), "runs_per_prompt": runs, "endpoints": {}, "rows": []}

    for name, base in ENDPOINTS.items():
        model = list_model(base)
        results["endpoints"][name] = {"base": base, "model": model, "up": model is not None}
        print(f"{name}: up={model is not None} model={model}", flush=True)

    for name, base in ENDPOINTS.items():
        ep = results["endpoints"][name]
        if not ep["up"]:
            continue
        model = ep["model"]
        for p in PROMPTS:
            # warmup
            print(f"warmup {name} {p['id']}...", flush=True)
            _ = chat_once(base, model, p)
            run_metrics = []
            for i in range(runs):
                print(f"run {i+1}/{runs} {name} {p['id']}...", flush=True)
                m = chat_once(base, model, p)
                m["endpoint"] = name
                m["prompt_id"] = p["id"]
                m["run"] = i + 1
                results["rows"].append(m)
                if m.get("ok"):
                    run_metrics.append(m)
                print(
                    f"  http={m.get('http')} wall={m.get('wall_s')}s "
                    f"tok/s={m.get('tok_s')} out={m.get('completion_tokens')}",
                    flush=True,
                )
            if run_metrics:
                walls = [x["wall_s"] for x in run_metrics if x.get("wall_s") is not None]
                toks = [x["tok_s"] for x in run_metrics if x.get("tok_s") is not None]
                results.setdefault("summary", {}).setdefault(name, {})[p["id"]] = {
                    "wall_s_mean": round(statistics.mean(walls), 3) if walls else None,
                    "tok_s_mean": round(statistics.mean(toks), 2) if toks else None,
                    "n": len(run_metrics),
                }

    out_dir = Path(r"D:\PhronesisVault\Operations\logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    json_path = out_dir / f"bench-qwen36-vs-qwythos-{stamp}.json"
    md_path = out_dir / f"bench-qwen36-vs-qwythos-{stamp}.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = [
        f"# Bench: Qwen3.6-35B-A3B abliterated vs Qwythos-9B — {results['at']}",
        "",
        "## Endpoints",
        "",
    ]
    for name, ep in results["endpoints"].items():
        lines.append(f"- **{name}**: `{ep['base']}` up={ep['up']} model=`{ep.get('model')}`")
    lines += ["", "## Summary (mean of timed runs)", ""]
    summary = results.get("summary") or {}
    for name, prompts in summary.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| prompt | wall_s mean | tok/s mean | n |")
        lines.append("|--------|-------------|------------|---|")
        for pid, s in prompts.items():
            lines.append(
                f"| {pid} | {s.get('wall_s_mean')} | {s.get('tok_s_mean')} | {s.get('n')} |"
            )
        lines.append("")
    lines += [
        "## Notes",
        "",
        "- Non-streaming: wall time is total request time; TTFT approximates prefill when server timings absent.",
        "- Qwen side uses MoE CPU offload (`--n-cpu-moe`); Qwythos is dense GPU-resident Q6_K.",
        f"- Full JSON: `{json_path}`",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {json_path}", flush=True)
    print(f"Wrote {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
