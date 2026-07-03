#!/usr/bin/env python3
"""Generate TriAttention calibration for the Q4 model.
Launches server briefly, sends calibration prompts, captures stats."""
import subprocess, time, os, urllib.request, json, signal

TQ_DIR = r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-30-turboquant-cuda13"
EXE = os.path.join(TQ_DIR, "llama-server.exe")
MODEL = r"D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf"
PORT = "8098"
CALIB_FILE = r"D:\PhronesisVault\Operations\logs\qwen14b-abliterated.triattention"
LOGDIR = r"D:\PhronesisVault\Operations\logs"
LOG_CAL = os.path.join(LOGDIR, "triattention-cal.log")

os.makedirs(LOGDIR, exist_ok=True)

# Calibration prompts covering diverse attention patterns
CALIB_PROMPTS = [
    "Write a Python function to sort a list of numbers.",
    "Explain what attention is in transformers.",
    "Summarize: The quick brown fox jumps over the lazy dog.",
    "Write a short story about a robot learning to paint.",
    "Decompose 1729 into its prime factors.",
    "Compare REST APIs and GraphQL for a web application.",
    "Translate 'Hello world' into French, Spanish, and German.",
    "Write a git commit message for a bug fix.",
]

print("=== TriAttention Calibration ===")

# Clean any existing calibration file
if os.path.exists(CALIB_FILE):
    os.remove(CALIB_FILE)
    print(f"Removed existing {CALIB_FILE}")

# Launch server with triattention stats collection
args = [
    EXE, "--port", PORT, "--host", "127.0.0.1",
    "-m", MODEL,
    "--fit", "on", "--fit-ctx", "8192", "--fit-target", "256",
    "--flash-attn", "on",
    "--cache-type-k", "turbo3", "--cache-type-v", "turbo3",
    "--no-mmap",
    "--triattention-stats", CALIB_FILE,
    "--triattention-budget", "4096",
    "--triattention-window", "256",
    "--triattention-log",
]

with open(LOG_CAL, "w") as out, open(LOG_CAL + ".err", "w") as err:
    proc = subprocess.Popen(args, stdout=out, stderr=err,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
print(f"Launched PID {proc.pid} on :{PORT}")

# Wait for readiness
for i in range(30):
    time.sleep(1)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/health")
        resp = urllib.request.urlopen(req, timeout=2)
        if resp.status == 200:
            print(f"READY after {i+1}s")
            break
    except:
        if i == 29:
            print("FAILED to start")
            os.kill(proc.pid, signal.SIGTERM)
            exit(1)

# Send calibration prompts
successful = 0
for prompt in CALIB_PROMPTS:
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100, "temperature": 0, "stream": False,
    }).encode()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/v1/chat/completions",
            data=payload, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=60)
        successful += 1
        print(f"  [{successful}/{len(CALIB_PROMPTS)}] {prompt[:50]}...")
    except Exception as e:
        print(f"  [ERR] {prompt[:50]}... {e}")

# Shutdown
os.kill(proc.pid, signal.SIGTERM)
print(f"\nSent {successful}/{len(CALIB_PROMPTS)} calibration prompts")

# Check calibration file
if os.path.exists(CALIB_FILE):
    size = os.path.getsize(CALIB_FILE)
    print(f"Calibration file: {CALIB_FILE} ({size:,} bytes)")
else:
    print(f"WARNING: Calibration file NOT created at {CALIB_FILE}")
    # Check logs for errors
    if os.path.exists(LOG_CAL + ".err"):
        with open(LOG_CAL + ".err") as f:
            lines = f.readlines()[-20:]
            for line in lines:
                if "triattention" in line.lower() or "error" in line.lower():
                    print(f"  LOG: {line.strip()}")
    exit(1)

print("TriAttention calibration complete")
