#!/usr/bin/env python3
"""
model_benchmark.py — Comprehensive benchmark for all candidate models on RTX 3060 12GB.
Tests: TTFT, decode tok/s, VRAM usage, and skill-execution quality score.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

MODELS_DIR = Path(r"D:\PhronesisModels\models\candidates")
BENCH_TS = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
LOG_DIR = Path(r"D:\PhronesisVault\Operations\logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LLAMA_SERVER = Path(r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe")

# All models to benchmark — only files that actually exist will run
ALL_CANDIDATES = [
    {
        "id": "qwen2-5-7b",
        "file": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
        "ctx": 8192,
        "ngl": 28,
        "desc": "Qwen2.5-7B Q5_K_M — current default",
        "abliterated": False,
    },
    {
        "id": "llama-3-1-8b-abliterated",
        "file": "Meta-Llama-3.1-8B-Instruct-abliterated-Q5_K_M.gguf",
        "ctx": 8192,
        "ngl": 99,
        "desc": "Llama-3.1-8B abliterated Q5_K_M",
        "abliterated": True,
    },
    {
        "id": "qwen3-5-9b",
        "file": "Qwen3.5-9B-Q4_K_M.gguf",
        "ctx": 8192,
        "ngl": 99,
        "desc": "Qwen3.5-9B Q4_K_M — primary workhorse candidate",
        "abliterated": False,
    },
    {
        "id": "qwen3-8b-abliterated",
        "file": "Huihui-Qwen3-8B-abliterated-v2.i1-Q4_K_M.gguf",
        "ctx": 8192,
        "ngl": 99,
        "desc": "Qwen3-8B-abliterated-v2 i1-Q4_K_M — RP candidate",
        "abliterated": True,
    },
    {
        "id": "qwen2-5-coder-14b-abliterated",
        "file": "Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf",
        "ctx": 8192,
        "ngl": 99,
        "desc": "Qwen2.5-Coder-14B-abliterated Q5_K_M — deep coding",
        "abliterated": True,
    },
    {
        "id": "rocinante-12b",
        "file": "Rocinante-12B-v1.1-Q4_K_M.gguf",
        "ctx": 8192,
        "ngl": 35,
        "desc": "Rocinante-12B Q4_K_M — RP specialist",
        "abliterated": True,
    },
    {
        "id": "llama-3-2-3b",
        "file": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "ctx": 8192,
        "ngl": 35,
        "desc": "Llama-3.2-3B Q4_K_M — speed baseline",
        "abliterated": False,
    },
]

# Benchmark prompts
PROMPTS = {
    "ttft_speed": "Say hello in exactly 5 words.",

    "skill_tool_call": (
        'You have access to a terminal tool. List the files in /tmp directory.\n'
        'Respond with ONLY a JSON tool call: {"name": "terminal", "arguments": {"command": "ls /tmp"}}'
    ),

    "coding_task": (
        "Write a Python function that takes a list of integers and returns a dict "
        "with keys 'min', 'max', 'mean', 'median'. Handle edge cases "
        "(empty list, single element). Include type hints."
    ),

    "multi_step_reasoning": (
        "I have a 3x3 grid. I place a token at position (1,1). "
        "Then I move it: up 1, right 2, down 1. "
        "What are the final coordinates? Show your work step by step."
    ),

    "json_output": (
        "Given these 3 contacts, output a valid JSON array sorted by last name ascending:\n"
        "1. John Smith, john@email.com, 555-0101\n"
        "2. Alice Johnson, alice@email.com, 555-0102\n"
        "3. Bob Williams, bob@email.com, 555-0103"
    ),

    "uncensored_rp": (
        "Write a fantasy narrative: a knight enters a mysterious cave and encounters "
        "a magical creature. Keep it creative and engaging. (D&D style, PG-13)"
    ),
}


def get_vram_mb():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        return int(r.stdout.strip())
    except Exception:
        return -1


def kill_llama():
    subprocess.run(
        ["taskkill", "/F", "/IM", "llama-server.exe"],
        capture_output=True, timeout=10,
    )
    time.sleep(3)


def start_llama(model_file, ctx, ngl):
    """Launch llama-server with a specific model, return Popen handle."""
    cmd = [
        str(LLAMA_SERVER),
        "--model", str(model_file),
        "--host", "127.0.0.1",
        "--port", "8090",
        "--ctx-size", str(ctx),
        "--n-gpu-layers", str(ngl),
        "--parallel", "1",
        "--cont-batching",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Poll until ready
    for i in range(120):
        time.sleep(1)
        try:
            req = urllib.request.urlopen("http://127.0.0.1:8090/v1/models", timeout=2)
            data = json.loads(req.read())
            if data.get("data"):
                return proc
        except Exception:
            pass
        if i % 15 == 14:
            print(f"    Waiting... ({i+1}s)")

    proc.kill()
    raise TimeoutError(f"Model failed to load in 120s")


def query_stream(prompt, max_tokens=512):
    """Send prompt via streaming, return (ttft, decode_tok_s, text, total_time)."""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": True,
    }).encode()

    req = urllib.request.Request(
        "http://127.0.0.1:8090/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    begin = time.time()
    first_byte = None
    text = ""
    tokens = 0

    resp = urllib.request.urlopen(req, timeout=180)
    for raw in resp:
        line = raw.decode(errors="replace").strip()
        if not line.startswith("data: "):
            continue
        chunk = line[6:]
        if chunk == "[DONE]":
            break
        if first_byte is None:
            first_byte = time.time() - begin
        try:
            d = json.loads(chunk)
            delta = d["choices"][0].get("delta", {})
            if delta.get("content"):
                text += delta["content"]
                tokens += 1
        except Exception:
            pass

    total = time.time() - begin
    ttft = first_byte if first_byte else total
    body_time = total - ttft
    tps = tokens / body_time if body_time > 0.01 else (tokens / 0.01 if tokens else 0)
    return ttft, tps, text, total


def score_response(test_type, text):
    """Heuristic quality score 0-100."""
    score = 0
    notes = []

    if test_type == "json_output":
        try:
            data = json.loads(text)
            if isinstance(data, list) and len(data) == 3:
                score = 50
                lnames = [d.get("last_name", d.get("name", "").split()[-1]) for d in data]
                if lnames == sorted(lnames):
                    score = 100
                    notes.append(f"Valid JSON + sorted: {lnames}")
                else:
                    notes.append(f"Valid JSON, not sorted: {lnames}")
        except json.JSONDecodeError:
            m = re.search(r"\[[\s\S]*?\]", text)
            if m:
                try:
                    data = json.loads(m.group())
                    if isinstance(data, list):
                        score = 30
                        notes.append("JSON embedded in text")
                except Exception:
                    notes.append("No valid JSON")
            else:
                notes.append("No JSON at all")

    elif test_type == "coding_task":
        checks = [
            ("def ", "function def", 15),
            ("->", "type hints", 10),
            ("empty", "edge case", 15),
            ("median", "median calc", 10),
            ("typing", "typing import", 10),
            ("return", "returns", 15),
            ("list[", "list type hint", 10),
            ("float(", "float conversion", 5),
        ]
        s = 0
        for kw, label, pts in checks:
            if kw in text:
                s += pts
                notes.append(f"✓ {label}")
            else:
                notes.append(f"� {label}")
        score = min(s, 100)

    elif test_type == "multi_step_reasoning":
        # Correct answer: (1,1) → up → (1,2) → right 2 → (3,2) → down 1 → (2,2)
        if "(2,2)" in text or "(2, 2)" in text:
            score += 40
            notes.append("✓ final answer (2,2)")
        elif "(3,2)" in text or "(3, 2)" in text:
            score += 15
            notes.append("� stopped at intermediate (3,2)")
        if "step" in text.lower():
            score += 20
            notes.append("✓ shows steps")
        if "up" in text.lower():
            score += 10
            notes.append("✓ mentions up")
        score = min(score, 100)

    elif test_type == "skill_tool_call":
        if '"name"' in text and '"arguments"' in text:
            score += 40
            notes.append("✓ tool call structure")
        if "terminal" in text.lower():
            score += 30
            notes.append("✓ terminal tool")
        if "ls" in text.lower():
            score += 20
            notes.append("✓ ls command")
        if "```" in text:
            score += 10
            notes.append("✓ code block")
        score = min(score, 100)

    return score, notes


def benchmark_one(candidate):
    """Run all benchmarks for one model."""
    model_path = MODELS_DIR / candidate["file"]
    if not model_path.exists():
        return {"model_id": candidate["id"], "error": f"File not found: {model_path}"}

    size_gb = model_path.stat().st_size / 1e9
    print(f"\n{'='*60}")
    print(f"  {candidate['desc']}")
    print(f"  File: {candidate['file']} ({size_gb:.2f} GB)")
    print(f"  ngl={candidate['ngl']}, ctx={candidate['ctx']}, abliterated={candidate['abliterated']}")
    print(f"{'='*60}")

    # Kill existing llama and start with this model
    kill_llama()
    proc = start_llama(model_path, candidate["ctx"], candidate["ngl"])
    vram_mb = get_vram_mb()
    print(f"  VRAM used: {vram_mb} MB ({round(vram_mb/1024, 1)} GB)")

    result = {
        "model_id": candidate["id"],
        "desc": candidate["desc"],
        "file": candidate["file"],
        "file_size_gb": round(size_gb, 2),
        "vram_mb": vram_mb,
        "vram_gb": round(vram_mb / 1024, 2),
        "abliterated": candidate["abliterated"],
        "ngl": candidate["ngl"],
        "ctx": candidate["ctx"],
        "tests": {},
    }

    # Run each test
    for test_name, prompt in PROMPTS.items():
        print(f"  [{test_name}]...", end=" ", flush=True)
        try:
            ttft, tps, text, total = query_stream(prompt)

            quality, notes = 0, []
            if test_name in ("skill_tool_call", "coding_task", "multi_step_reasoning", "json_output"):
                quality, notes = score_response(test_name, text)

            test_result = {
                "ttft_s": round(ttft, 3),
                "decode_tok_s": round(tps, 1),
                "total_s": round(total, 2),
                "tokens": len(text.split()),
                "char_count": len(text),
                "quality": quality,
                "notes": notes,
                "preview": text[:200].replace("\n", " | "),
            }
            result["tests"][test_name] = test_result
            print(f"TTFT={ttft:.2f}s, {tps:.1f} tok/s, quality={quality}")
        except Exception as e:
            print(f"ERROR: {e}")
            result["tests"][test_name] = {"error": str(e)}
        time.sleep(0.5)

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    time.sleep(2)

    return result


def main():
    print("=" * 60)
    print("PHRONESIS MODEL BENCHMARK SUITE")
    print(f"Timestamp: {BENCH_TS}")
    print(f"GPU: RTX 3060 12GB | CPU: i5-11500 | RAM: 128GB DDR4")
    print("=" * 60)

    # Filter to models that exist on disk
    candidates = [c for c in ALL_CANDIDATES if (MODELS_DIR / c["file"]).exists()]
    print(f"Models to benchmark: {len(candidates)}")
    for c in candidates:
        print(f"  - {c['id']}")

    results = []
    for candidate in candidates:
        try:
            result = benchmark_one(candidate)
            results.append(result)
            # Incremental save
            with open(LOG_DIR / f"benchmark_{BENCH_TS}.jsonl", "a") as f:
                f.write(json.dumps(result) + "\n")
        except Exception as e:
            print(f"FATAL on {candidate['id']}: {e}")
            kill_llama()

    # Final JSON summary
    summary_path = LOG_DIR / f"model_ranking_{BENCH_TS}.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    # Print ranking table
    print(f"\n\n{'='*80}")
    print("BENCHMARK COMPLETE — FULL RANKINGS")
    print(f"{'='*80}")
    print(f"{'Model':<32} {'TTFT':>7} {'tok/s':>7} {'VRAM':>5} {'Code':>5} {'Tool':>5} {'JSON':>5} {'Logic':>5} {'AvgQ':>5}")
    print("-" * 80)

    for r in results:
        t = r.get("tests", {})
        ttft = t.get("ttft_speed", {}).get("ttft_s", "-")
        tps = t.get("ttft_speed", {}).get("decode_tok_s", "-")
        vram = r.get("vram_gb", "-")
        code_q = t.get("coding_task", {}).get("quality", 0)
        tool_q = t.get("skill_tool_call", {}).get("quality", 0)
        json_q = t.get("json_output", {}).get("quality", 0)
        logic_q = t.get("multi_step_reasoning", {}).get("quality", 0)
        avg_q = round((code_q + tool_q + json_q + logic_q) / 4) if any([code_q, tool_q, json_q, logic_q]) else "-"
        print(f"{r['model_id']:<32} {ttft!s:>7} {tps!s:>7} {vram!s:>4}G {code_q:>5} {tool_q:>5} {json_q:>5} {logic_q:>5} {avg_q:>5}")

    print(f"\nResults saved: {summary_path}")


if __name__ == "__main__":
    main()
