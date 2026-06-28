#!/usr/bin/env python3
"""Quick retest of Qwen3.5-9B to fix timing/streaming issues."""
import json, time, urllib.request, subprocess
from pathlib import Path

LLAMA = Path(r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe")
MODEL = Path(r"D:\PhronesisModels\models\candidates\Qwen3.5-9B-Q4_K_M.gguf")

# Kill existing
subprocess.run(["taskkill","/F","/IM","llama-server.exe"], capture_output=True, timeout=10)
time.sleep(3)

# Start with all layers on GPU
cmd = [str(LLAMA),"--model",str(MODEL),"--host","127.0.0.1","--port","8090",
       "--ctx-size","8192","--n-gpu-layers","99","--parallel","1","--cont-batching"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Wait for ready
for i in range(60):
    time.sleep(1)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8090/v1/models", timeout=2)
        if json.loads(r.read()).get("data"):
            break
    except: pass

print("Model loaded. VRAM baseline check...")
vram_base = int(subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],
                               capture_output=True, text=True).stdout.strip())
print(f"VRAM total used: {vram_base} MB")

# Test 1: Simple TTFT with manual stream parsing
print("\n=== TEST: Simple prompt ===")
payload = json.dumps({
    "messages": [{"role":"user","content":"Say hello in exactly 5 words."}],
    "max_tokens": 50, "temperature": 0.1, "stream": True,
}).encode()
req = urllib.request.Request("http://127.0.0.1:8090/v1/chat/completions",
                             data=payload, headers={"Content-Type":"application/json"}, method="POST")

begin = time.time()
resp = urllib.request.urlopen(req, timeout=30)
raw_chunks = []
first = None
for raw in resp:
    line = raw.decode(errors="replace").strip()
    raw_chunks.append(line)
    if first is None and line.startswith("data: ") and line[6:] != "[DONE]":
        first = time.time() - begin

ttft = first if first else time.time()-begin

# Parse content
text = ""
tokens = 0
for line in raw_chunks:
    if not line.startswith("data: "): continue
    chunk = line[6:]
    if chunk == "[DONE]": continue
    try:
        d = json.loads(chunk)
        if d["choices"][0].get("delta",{}).get("content"):
            text += d["choices"][0]["delta"]["content"]
            tokens += 1
    except: pass

total = time.time()-begin
body = total - ttft
tps = tokens/body if body > 0.01 else tokens/0.01

print(f"TTFT: {ttft:.3f}s")
print(f"Total: {total:.3f}s")
print(f"Tokens: {tokens}")
print(f"Decode tok/s: {tps:.1f}")
print(f"Response: '{text.strip()}'")
print(f"Raw chunks received: {len(raw_chunks)}")

# Test 2: Longer coding prompt
print("\n=== TEST: Coding prompt (100+ tokens) ===")
payload2 = json.dumps({
    "messages": [{"role":"user","content":"Write a Python function that takes a list of integers and returns a dict with keys min, max, mean, median. Include type hints and handle edge cases."}],
    "max_tokens": 256, "temperature": 0.1, "stream": True,
}).encode()
req2 = urllib.request.Request("http://127.0.0.1:8090/v1/chat/completions",
                              data=payload2, headers={"Content-Type":"application/json"}, method="POST")

begin2 = time.time()
resp2 = urllib.request.urlopen(req2, timeout=60)
first2 = None
text2 = ""
tokens2 = 0
for raw in resp2:
    line = raw.decode(errors="replace").strip()
    if not line.startswith("data: "): continue
    chunk = line[6:]
    if chunk == "[DONE]": continue
    if first2 is None:
        first2 = time.time() - begin2
    try:
        d = json.loads(chunk)
        if d["choices"][0].get("delta",{}).get("content"):
            text2 += d["choices"][0]["delta"]["content"]
            tokens2 += 1
    except: pass

total2 = time.time() - begin2
body2 = total2 - first2 if first2 else total2
tps2 = tokens2/body2 if body2 > 0.01 else tokens2/0.01

print(f"TTFT: {first2:.3f}s" if first2 else "TTFT: N/A")
print(f"Total: {total2:.3f}s")
print(f"Tokens: {tokens2}")
print(f"Decode tok/s: {tps2:.1f}")
print(f"Response preview: {text2[:200].strip()}")

proc.terminate()
proc.wait(timeout=5)
print("\nDone.")
