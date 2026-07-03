#!/usr/bin/env python3
"""Smoke-test the TurboQuant binary with TurboQuant KV cache on a tiny model."""
import subprocess, sys, time, os, urllib.request, json

EXE = r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-30-turboquant-cuda13\llama-server.exe"
MODEL = r"D:\PhronesisModels\models\candidates\gemma-2-2b-it-Q4_K_M.gguf"
PORT = "8099"
LOGOUT = r"D:\PhronesisVault\Operations\logs\tq-smoke.log"
LOGERR = r"D:\PhronesisVault\Operations\logs\tq-smoke.err.log"

args = [
    EXE, "--port", PORT, "--host", "127.0.0.1",
    "-m", MODEL,
    "--fit", "on", "--fit-ctx", "8192", "--fit-target", "512",
    "--flash-attn", "on",
    "--cache-type-k", "turbo3",  # <-- TurboQuant 3-bit!
    "--cache-type-v", "turbo3",
    "--no-mmap",
]

os.makedirs(os.path.dirname(LOGOUT), exist_ok=True)
with open(LOGOUT, "w") as out, open(LOGERR, "w") as err:
    proc = subprocess.Popen(
        args, stdout=out, stderr=err,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
print(f"Launched PID {proc.pid} on port {PORT}")

# Poll for readiness
for i in range(20):
    time.sleep(1)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/health")
        resp = urllib.request.urlopen(req, timeout=2)
        if resp.status == 200:
            print(f"READY after {i+1}s")
            break
    except Exception:
        if i == 19:
            print("FAILED")
            sys.exit(1)

# Quick inference test
payload = json.dumps({
    "messages": [{"role": "user", "content": "Say OK in one word."}],
    "max_tokens": 5, "temperature": 0,
}).encode()
req = urllib.request.Request(
    f"http://127.0.0.1:{PORT}/v1/chat/completions",
    data=payload,
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req, timeout=15)
data = json.loads(resp.read())
content = data["choices"][0]["message"]["content"]
print(f"Inference: {content}")
print(f"Model: {data['model']}")
print(f"Tokens: {data['usage']['prompt_tokens']} in, {data['usage']['completion_tokens']} out")

# Cleanup
import signal
os.kill(proc.pid, signal.SIGTERM)
print("TurboQuant smoke test PASSED")
