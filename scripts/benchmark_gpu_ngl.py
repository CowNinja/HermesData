#!/usr/bin/env python3
"""Verify GPU ngl and measure inference tokens/sec on 8090."""
from __future__ import annotations

import json
import time
import urllib.request

ROUTER = "http://127.0.0.1:8090/v1/chat/completions"
LOGICAL = "qwen2-5-7b"


def main() -> int:
    models = json.loads(
        urllib.request.urlopen("http://127.0.0.1:8090/v1/models", timeout=15).read()
    )
    entry = next(m for m in models["data"] if m["id"] == LOGICAL)
    args = entry["status"]["args"]
    ngl = "?"
    for i, arg in enumerate(args):
        if arg == "--n-gpu-layers" and i + 1 < len(args):
            ngl = args[i + 1]
    preset = entry["status"].get("preset", "")
    print(f"model={LOGICAL} status={entry['status']['value']} ngl={ngl}")
    for line in preset.splitlines():
        if any(k in line for k in ("ngl", "ctx-size", "parallel")):
            print(f"  {line}")

    body = {
        "model": LOGICAL,
        "messages": [{"role": "user", "content": "Write exactly 80 words about a forge."}],
        "max_tokens": 120,
        "temperature": 0.7,
    }
    for label in ("warm", "bench"):
        started = time.time()
        req = urllib.request.Request(
            ROUTER,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        elapsed = round(time.time() - started, 2)
        timings = data.get("timings") or {}
        usage = data.get("usage") or {}
        print(
            f"{label}: elapsed={elapsed}s "
            f"tps={timings.get('predicted_per_second')} "
            f"pred_tokens={timings.get('predicted_n')} "
            f"completion_tokens={usage.get('completion_tokens')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
