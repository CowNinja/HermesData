#!/usr/bin/env python3
"""nanodb_benchmark.py — No-agent nanoDB benchmark snapshot.

Calls the local sovereign proxy on :8091 and captures a simple benchmark
(per-token latency, throughput) and logs it to D:/HermesData/benchmark-results/.

Called by cron with `no_agent: True`.  Silent on success (watchdog pattern).
"""

import json, os, time, sys, urllib.request, urllib.error, datetime

SOVEREIGN_URL = "http://127.0.0.1:8091/v1/chat/completions"
MODEL = "phronesis-sovereign-auto"
OUTPUT_DIR = r"D:\HermesData\benchmark-results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

TEST_PROMPTS = [
    "What is 2+2? Answer in one word.",
    "Write a haiku about silicon valley.",
    "Is the sky blue? Answer yes or no.",
]

def call_model(prompt: str) -> dict:
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        SOVEREIGN_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=30)
    elapsed = time.time() - t0
    data = json.loads(resp.read())
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return {"latency_s": round(elapsed, 2), "tokens": tokens, "tps": round(tokens / elapsed, 1) if elapsed > 0 else 0}

def main():
    results = []
    health_ok = True
    try:
        urllib.request.urlopen("http://127.0.0.1:8091/v1/models", timeout=5)
    except Exception:
        health_ok = False

    if not health_ok:
        print(f"nanoDB SKIP: sovereign proxy :8091 unreachable at {datetime.datetime.now().isoformat()}")
        sys.exit(0)

    for i, prompt in enumerate(TEST_PROMPTS):
        try:
            r = call_model(prompt)
            r["prompt_index"] = i
            results.append(r)
        except Exception as e:
            results.append({"prompt_index": i, "error": str(e)})

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "model": MODEL,
        "results": results,
    }

    path = os.path.join(OUTPUT_DIR, f"nanodb_{timestamp}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)

    avg_tps = sum(r.get("tps", 0) for r in results if "tps" in r) / max(len([r for r in results if "tps" in r]), 1)
    print(f"nanoDB: {len(results)} probes, avg {avg_tps:.1f} t/s → {path}")

if __name__ == "__main__":
    main()
