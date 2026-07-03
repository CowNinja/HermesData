#!/usr/bin/env python3
"""Full switchover: deploy Q4_K_M + TurboQuant on 8090.
Steps:
1. Stop current 8090
2. Start with Q4_K_M + --cache-type-k/v turbo3 + TriAttention
3. Verify health
4. Run benchmark
"""
import subprocess, sys, time, os, json, urllib.request, signal

# === CONFIG ===
TQ_DIR = r"D:\PhronesisModels\binaries\test-prebuilts\2026-06-30-turboquant-cuda13"
EXE = os.path.join(TQ_DIR, "llama-server.exe")
MODEL = r"D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf"
OLD_MODEL = r"D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf"
PORT = "8090"
LOGDIR = r"D:\PhronesisVault\Operations\logs"
LOG_OUT = os.path.join(LOGDIR, "llama-8090-tq.log")
LOG_ERR = os.path.join(LOGDIR, "llama-8090-tq.err.log")

os.makedirs(LOGDIR, exist_ok=True)

def check_file(path, label):
    if not os.path.exists(path):
        print(f"ERROR: {label} not found at {path}")
        return False
    size_gb = os.path.getsize(path) / 1e9
    print(f"{label}: {os.path.basename(path)} ({size_gb:.1f} GB)")
    return True

def wait_for_port(port, timeout=30):
    for i in range(timeout):
        time.sleep(1)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status == 200:
                return i + 1
        except Exception:
            continue
    return None

def stop_port(port):
    """Find and kill any process on port."""
    try:
        r = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True)
                print(f"Stopped PID {pid} on :{port}")
                time.sleep(2)
                return
    except Exception:
        pass
    print(f"Port {port}: nothing to stop")

def run_benchmark(port):
    """Quick benchmark: short, medium, long prompts."""
    prompts = {
        "short": "Say hello.",
        "medium": "Write a Python function to calculate fibonacci numbers.",
        "long": "Write a detailed architectural analysis of how a transformer model processes attention, including the QKV projection, scaled dot-product attention, multi-head splitting, and the feed-forward network. Include code examples.",
    }
    results = {}
    for name, prompt in prompts.items():
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200, "temperature": 0, "stream": False,
        }).encode()
        try:
            start = time.time()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=120)
            latency = time.time() - start
            data = json.loads(resp.read())
            usage = data.get("usage", {})
            out_tokens = usage.get("completion_tokens", 0)
            tps = out_tokens / latency if latency > 0 else 0
            results[name] = {
                "latency_sec": round(latency, 2),
                "out_tokens": out_tokens,
                "tps": round(tps, 1),
            }
            print(f"  {name:8s}: {tps:.1f} t/s ({latency:.1f}s, {out_tokens} tok)")
        except Exception as e:
            results[name] = {"error": str(e)}
            print(f"  {name:8s}: FAILED - {e}")
    return results

# === MAIN ===
print("=" * 60)
print("PHASE 3: DEPLOY Q4 + TURBOQUANT ON 8090")
print("=" * 60)

# 1. Verify files
if not check_file(MODEL, "Q4_K_M model") or not check_file(EXE, "TurboQuant binary"):
    print("\nERROR: Missing required files.")
    print(f"Download Q4 model to:\n  {MODEL}")
    sys.exit(1)

# 2. Get VRAM baseline
try:
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                        "--format=csv,noheader"], capture_output=True, text=True)
    print(f"\nVRAM before: {r.stdout.strip()}")
except:
    pass

# 3. Stop 8090
print("\nStopping current 8090...")
stop_port(PORT)
wait = wait_for_port(PORT, timeout=5)
if wait:
    print("WARNING: Port still active after kill")

# 4. Launch with Q4 + TurboQuant + TriAttention
print("\nLaunching TurboQuant server...")
args = [
    EXE, "--port", PORT, "--host", "127.0.0.1",
    "-m", MODEL,
    "--fit", "on", "--fit-ctx", "65536", "--fit-target", "512",
    "--flash-attn", "on",
    "--cache-type-k", "turbo3",
    "--cache-type-v", "turbo3",
    "--no-mmap",
    "--cont-batching",
    "--parallel", "1",
    "--batch-size", "1024", "--ubatch-size", "512",
    "--jinja",
]
# Add TriAttention if we have a calibration file
TRIATTEN_FILE = os.path.join(LOGDIR, "model.triattention")
if os.path.exists(TRIATTEN_FILE):
    args += ["--triattention-stats", TRIATTEN_FILE,
             "--triattention-budget", "4096",
             "--triattention-window", "256"]
    print("  + TriAttention enabled")

with open(LOG_OUT, "w") as out, open(LOG_ERR, "w") as err:
    proc = subprocess.Popen(
        args, stdout=out, stderr=err,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
print(f"Launched PID {proc.pid}")

# 5. Wait for readiness
ready_in = wait_for_port(PORT, timeout=60)
if not ready_in:
    print("FAILED: Server did not start within 60s")
    # Print last lines of error log
    if os.path.exists(LOG_ERR):
        with open(LOG_ERR) as f:
            print("Last 20 lines of error log:")
            print("".join(f.readlines()[-20:]))
    sys.exit(1)
print(f"READY after {ready_in}s")

# 6. Check VRAM after
try:
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                        "--format=csv,noheader"], capture_output=True, text=True)
    print(f"VRAM after:  {r.stdout.strip()}")
    parts = r.stdout.strip().split(",")
    used = int(parts[0].split()[0])
    total = int(parts[1].split()[0])
    free = total - used
    print(f"VRAM free:   {free} MiB ({free/total*100:.1f}%)")
except:
    pass

# 7. Model info
try:
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/models")
    resp = urllib.request.urlopen(req, timeout=5)
    data = json.loads(resp.read())
    for m in data.get("data", []):
        print(f"Model: {m.get('id', '?')}")
except Exception as e:
    print(f"Model query: {e}")

# 8. Benchmark
print("\nRunning benchmark...")
bench = run_benchmark(PORT)

# 9. Summary
print("\n" + "=" * 60)
print("BENCHMARK RESULTS (Q4_K_M + TurboQuant)")
print("=" * 60)
for name, r in bench.items():
    if "error" in r:
        print(f"  {name}: ERROR - {r['error']}")
    else:
        print(f"  {name}: {r['tps']} t/s  ({r['latency_sec']}s for {r['out_tokens']} tok)")

# 10. Save results
summary = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "model": MODEL.replace("\\", "/").split("/")[-1],
    "binary": "turboquant-8671",
    "kv_cache": "turbo3",
    "flags": {
        "fit_on": True, "fit_ctx": 65536, "fit_target": 512,
        "flash_attn": "on",
        "cache_type_k": "turbo3", "cache_type_v": "turbo3",
        "no_mmap": True, "cont_batching": True,
    },
    "vram": {"used_mib": used, "total_mib": total, "free_mib": free},
    "benchmark": bench,
}
result_path = os.path.join(LOGDIR, "benchmark-turboquant-q4.json")
with open(result_path, "w") as f:
    json.dump(summary, f, indent=2)
print(f"\nBenchmark saved to {result_path}")

# Record to nanoDB
try:
    sys.path.insert(0, r"D:\HermesData\scripts")
    from nanodb import record_dispatch, record_model, benchmark_snapshot
    record_model("qwen25-14b-q4-tq", quantization="q4_k_m",
                 vram_estimate_gb=round(free / 1024, 2))
    benchmark_snapshot("turboquant-q4_deploy")
except Exception as e:
    print(f"nanoDB record: {e}")

print("\nDEPLOYMENT COMPLETE")
