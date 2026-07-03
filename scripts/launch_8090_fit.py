#!/usr/bin/env python3
"""Launch 8090 with --fit on profile. Detached, logged, verified."""
import subprocess, sys, time, os, json, urllib.request

MODEL = r"D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf"
EXE = r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"
LOGDIR = r"D:\PhronesisVault\Operations\logs"
PORT = "8090"

args = [
    EXE,
    "--port", PORT, "--host", "127.0.0.1",
    "-m", MODEL,
    "--fit", "on", "--fit-ctx", "65536", "--fit-target", "512",
    "--flash-attn", "on",
    "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
    "--threads", "8",
    "--batch-size", "1024", "--ubatch-size", "512",
    "--no-mmap",
    "--cont-batching",
    "--jinja",
    "--parallel", "1",
]

log_out = os.path.join(LOGDIR, "llama-8090-fit.log")
log_err = os.path.join(LOGDIR, "llama-8090-fit.err.log")
os.makedirs(LOGDIR, exist_ok=True)

with open(log_out, "w") as out, open(log_err, "w") as err:
    proc = subprocess.Popen(
        args,
        stdout=out, stderr=err,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )

print(f"Launched PID {proc.pid} on port {PORT}")
print(f"Log: {log_out}")
print(f"Err: {log_err}")

# Poll for readiness
for i in range(30):
    time.sleep(1)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/health")
        resp = urllib.request.urlopen(req, timeout=2)
        if resp.status == 200:
            print(f"READY after {i+1}s")
            break
    except Exception:
        if i == 29:
            print("FAILED to start after 30s")
            sys.exit(1)
        continue

# Print model info
try:
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/models")
    resp = urllib.request.urlopen(req, timeout=2)
    data = json.loads(resp.read())
    for m in data.get("data", []):
        print(f"Model: {m.get('id')}")
except Exception as e:
    print(f"Model query failed: {e}")

print("DONE")
