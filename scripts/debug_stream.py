#!/usr/bin/env python3
"""Debug Qwen3.5-9B streaming response format - load model first."""
import json, time, urllib.request, subprocess
from pathlib import Path

LLAMA = Path(r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe")
MODEL = Path(r"D:\PhronesisModels\models\candidates\Qwen3.5-9B-Q4_K_M.gguf")

subprocess.run(["taskkill","/F","/IM","llama-server.exe"], capture_output=True, timeout=10)
time.sleep(3)

cmd = [str(LLAMA),"--model",str(MODEL),"--host","127.0.0.1","--port","8090",
       "--ctx-size","8192","--n-gpu-layers","99","--parallel","1","--cont-batching"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

for i in range(60):
    time.sleep(1)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8090/v1/models", timeout=2)
        if json.loads(r.read()).get("data"):
            print(f"Model loaded in {i+1}s")
            break
    except: pass

# Send a test prompt
payload = json.dumps({
    "messages": [{"role":"user","content":"Say hello in 5 words."}],
    "max_tokens": 32, "temperature": 0.1, "stream": True,
}).encode()
req = urllib.request.Request("http://127.0.0.1:8090/v1/chat/completions",
                             data=payload, headers={"Content-Type":"application/json"}, method="POST")

begin = time.time()
resp = urllib.request.urlopen(req, timeout=30)

count = 0
text = ""
for raw in resp:
    line = raw.decode(errors="replace").strip()
    elapsed = time.time() - begin
    if line.startswith("data: ") and line[6:] != "[DONE]":
        chunk_data = line[6:]
        try:
            d = json.loads(chunk_data)
            content = d.get("choices",[{}])[0].get("delta",{}).get("content","")
            if not content:
                # Print first few chunks to see the structure
                if count < 10:
                    print(f"[{elapsed:.3f}s] chunk #{count}: {json.dumps(d, indent=2)[:300]}")
            text += content
        except:
            if count < 10:
                print(f"[{elapsed:.3f}] chunk #{count}: RAW (not JSON): {chunk_data[:200]}")
        count += 1
    elif line == "data: [DONE]":
        print(f"\n[{elapsed:.3f}s] DONE after {count} chunks")
        break

print(f"\nFinal text: '{text}'")
print(f"Chars collected: {len(text)}")

proc.terminate()
proc.wait(timeout=5)
print("Done.")
