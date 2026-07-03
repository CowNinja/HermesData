#!/usr/bin/env python3
"""
bench_router_q4_vs_q5.py — Benchmark Q5_K_M vs Q4_K_M on the 8090 router.

Test matrix:
  - Models: qwen25-7b-q5 vs qwen25-7b-q4
  - Tasks: code_generation, reasoning, chat, json_generation
  - Metrics: TTFT (ms), total_time (ms), tokens_per_sec, tokens_generated
  - VRAM snapshot via nvidia-smi before/after

Usage:
  python bench_router_q4_vs_q5.py --url http://127.0.0.1:8090
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "http://127.0.0.1:8090"
MODELS = ["qwen25-7b-q5", "qwen25-7b-q4"]
PROMPTS = {  # noqa: E221
    "code_generation": "Write a Python function called `fibonacci(n)` that returns the nth Fibonacci number using memoization. Include type hints and a docstring.",
    "reasoning": "Explain why the sky is blue, step by step, in 3-4 sentences.",
    "chat": "What are three interesting facts about octopuses?",
    "json_generation": 'Return a JSON object with exactly 3 fields: "name" (string, a city), "population" (integer), "country" (string). Return ONLY valid JSON, no other text.'
}
MAX_TOKENS = 256
WARMUP_TOKENS = 16

def post_chat(model, prompt, max_tokens=MAX_TOKENS, base_url=None):
    """POST to /v1/chat/completions, return (response_dict, elapsed_ms)."""
    if base_url is None:
        base_url = URL
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            data = json.loads(body)
    except Exception as e:
        return {"error": str(e)}, 0
    elapsed_ms = (time.time() - t0) * 1000
    return data, elapsed_ms

def get_vram_mb():
    """Get NVIDIA VRAM usage in MB via nvidia-smi."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        return int(r.stdout.strip().split("\n")[0])
    except:
        return -1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    args = parser.parse_args()

    log_dir = Path(r"D:\PhronesisVault\Operations\logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    out_file = log_dir / f"bench-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"

    bench_url = args.url

    # Check health
    try:
        with urllib.request.urlopen(f"{bench_url}/health", timeout=5) as r:
            print(f"Health: {r.read().decode()}")
    except Exception as e:
        print(f"HEALTH FAIL: {e}")
        sys.exit(1)

    results = {}
    print(f"\n{'='*70}")
    print(f"BENCH: Q4_K_M vs Q5_K_M — {datetime.now().isoformat()}")
    print(f"URL: {bench_url}")
    print(f"{'='*70}\n")

    for model in MODELS:
        print(f"\n{'─'*40}")
        print(f"Model: {model}")
        print(f"{'─'*40}")
        model_results = {}

        # VRAM before loading model
        vram_before = get_vram_mb()
        print(f"  VRAM before: {vram_before} MB")

        # Warmup request to load model into VRAM
        print("  Warming up (loading model)...")
        warmup_resp, warmup_ms = post_chat(model, "Say hi.", WARMUP_TOKENS, base_url=bench_url)
        print(f"  Warmup: {warmup_ms:.0f}ms")

        vram_after = get_vram_mb()
        vram_used = vram_after - vram_before if vram_before > 0 else 0
        print(f"  VRAM after load: {vram_after} MB (delta ~{vram_used} MB)")

        for task_name, prompt in PROMPTS.items():
            resp, elapsed_ms = post_chat(model, prompt, base_url=bench_url)
            if "error" in resp:
                print(f"  [{task_name}] ERROR: {resp['error']}")
                model_results[task_name] = {"error": resp['error']}
                continue

            usage = resp.get("usage", {})
            timings = resp.get("timings", {})
            comp_tokens = usage.get("completion_tokens", 0)
            prompt_tokens = usage.get("prompt_tokens", 0)
            predicted_ms = timings.get("predicted_ms", 0)
            prompt_ms = timings.get("prompt_ms", 0)
            tps = timings.get("predicted_per_second", 0)

            # Extract content for quality check
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            is_json = False
            if task_name == "json_generation":
                try:
                    json.loads(content.strip())
                    is_json = True
                except:
                    is_json = False

            entry = {
                "task": task_name,
                "total_ms": round(elapsed_ms, 1),
                "prompt_ms": round(prompt_ms, 1),
                "predict_ms": round(predicted_ms, 1),
                "tokens": comp_tokens,
                "tokens_per_sec": round(tps, 1),
                "prompt_tokens": prompt_tokens,
                "valid_json": is_json,
                "content_preview": content[:120]
            }
            model_results[task_name] = entry
            print(f"  [{task_name:20s}] {elapsed_ms:8.0f}ms total | {prompt_ms:6.0f}ms prompt | {tps:6.1f} t/s | {comp_tokens:3d} tokens | JSON_ok={is_json}")

            # Small delay between requests
            time.sleep(0.5)

        model_results["_vram_mb"] = vram_after
        model_results["_vram_delta_mb"] = vram_used
        results[model] = model_results

    # Write results to JSONL log
    with open(out_file, "w") as f:
        f.write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": bench_url,
            "models": MODELS,
            "tasks": list(PROMPTS.keys()),
            "results": results
        }, indent=2))

    # Print summary comparison
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    q5 = results.get("qwen25-7b-q5", {})
    q4 = results.get("qwen25-7b-q4", {})

    q5_tps = [v.get("tokens_per_sec", 0) for k, v in q5.items() if not k.startswith("_") and "tokens_per_sec" in v]
    q4_tps = [v.get("tokens_per_sec", 0) for k, v in q4.items() if not k.startswith("_") and "tokens_per_sec" in v]

    q5_avg = sum(q5_tps) / len(q5_tps) if q5_tps else 0
    q4_avg = sum(q4_tps) / len(q4_tps) if q4_tps else 0

    print(f"  Q5_K_M avg TPS: {q5_avg:.1f}  VRAM: {q5.get('_vram_delta_mb', '?')} MB")
    print(f"  Q4_K_M avg TPS: {q4_avg:.1f}  VRAM: {q4.get('_vram_delta_mb', '?')} MB")
    ratio = q4_avg / q5_avg if q5_avg > 0 else 0
    print(f"  Q4/Q5 speed ratio: {ratio:.2f}x")
    print(f"\n  Log written to: {out_file}")

    return results

if __name__ == "__main__":
    main()
