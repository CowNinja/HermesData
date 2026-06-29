# Phronesis Sovereign — Operations & Crash Recovery

> Centralized PowerShell scripts for recovering the local AI stack after a crash, starting/stopping services, and day-to-day operations.

## Quick Start — After a Crash

**Just run ONE script to get everything back online (recommended):**

```powershell
PS> D:\HermesData\scripts\ops\01-recovery.ps1
```

That's it. It kills zombie processes, starts all backends in order, waits for readiness, and prints a health report.

---

## Architecture

```
Hermes Agent ──→ openai-proxy (8091) ──→ llama.cpp (8090)
                  (routes, caches,                    (GPU inference,
                   circuit-breaks)                   GGUF model)
```

| Port | Service | Role |
|------|---------|------|
| `8091` | `sovereign_openai_proxy.py` | OpenAI-compatible gateway (routing, caching, circuit breaker) |
| `8090` | `llama-server.exe` | Native CUDA inference backend |
| `11434` | Ollama | CPU-fallback inference (independent) |

---

## Script Reference

### 01 — `01-recovery.ps1` — Full crash recovery *(run this first)*

Kills all managed processes (python/llama-server), starts llama.cpp on 8090, waits for `/v1/models` to respond, starts the proxy on 8091, then prints a health summary.

```powershell
PS> D:\HermesData\scripts\ops\01-recovery.ps1
```

**What it does (in order):**
1. `taskkill /F /IM llama-server.exe`
2. `taskkill /F /IM python.exe`
3. Waits 2s for ports to free
4. Launches `llama-server.exe` with your default model
5. Polls `http://127.0.0.1:8090/v1/models` until ready (max 120s)
6. Launches `python sovereign_openai_proxy.py` on port 8091
7. Prints proxy health + model discovery output

**When to use:** After any crash, before asking me to do anything else.

---

### 02 — `02-start-llama.ps1` — Start llama.cpp only

Use this when you want to restart the LLM backend without touching the proxy. Supports `-Model` to override which GGUF to load.

```powershell
# Start with default model
PS> D:\HermesData\scripts\ops\02-start-llama.ps1

# Start with a specific GGUF
PS> D:\HermesData\scripts\ops\02-start-llama.ps1 -Model "D:\PhronesisModels\models\candidates\Qwen3.5-9B-Q4_K_M.gguf"
```

**Options:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Model` | `D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf` | GGUF file to load |
| `-Port` | `8090` | Port to bind |
| `-CtxSize` | `8192` | Context window size |
| `-Ngl` | `99` | GPU layers (99 = all on GPU) |
| `-ContBatching` | `$true` | Enable continuous batching |

---

### 03 — `03-start-proxy.ps1` — Start MoE proxy only

Use this to restart just the gateway without reloading the model into VRAM.

```powershell
PS> D:\HermesData\scripts\ops\03-start-proxy.ps1
```

**Options:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Port` | `8091` | Port to bind |
| `-Host` | `127.0.0.1` | Bind address |

---

### 04 — `04-status.ps1` — Health check all

Runs status on every managed port, prints what's up/down, and shows which llama.cpp instance is serving.

```powershell
PS> D:\HermesData\scripts\ops\04-status.ps1
```

**Output example:**
```
[8091] PROXY  → OK (qwen2.5-coder-14b, circuit=closed, cache=12 entries)
[8090] LLAMA  → OK (Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M, ngl=99)
[DONE] 2/2 services healthy
```

---

### 05 — `05-stop-all.ps1` — Kill all managed processes

Graceful shutdown of everything this ops dir manages. No args.

```powershell
PS> D:\HermesData\scripts\ops\05-stop-all.ps1
```

---

### 06 — `06-smoke-test.ps1` — End-to-end test

Sends a test prompt through the proxy to llama.cpp and back. Verifies the entire chain is responding correctly.

```powershell
# Default short test (recommended for daily check)
PS> D:\HermesData\scripts\ops\06-smoke-test.ps1

# Longer benchmark-style test
PS> D:\HermesData\scripts\ops\06-smoke-test.ps1 -LongTest
```

**What it tests:**
1. Proxy is reachable at 8091
2. Backend is reachable at 8090
3. Proxy routes requests to backend
4. Response parses as valid OpenAI format
5. Reports estimated tok/s

---

### 07 — `07-switch-model.ps1` — Swap model without restarting proxy

Gracefully transitions llama.cpp to a new GGUF. Kills the old llama-server, starts with new model, waits for readiness.

```powershell
# Switch to Qwen3.5-9B (faster, for RP/casual)
PS> D:\HermesData\scripts\ops\07-switch-model.ps1 -Model "D:\PhronesisModels\models\candidates\Qwen3.5-9B-Q4_K_M.gguf"

# Switch to third model you download later
PS> D:\HermesData\scripts\ops\07-switch-model.ps1 -Model "D:\PhronesisModels\models\candidates\Qwythos-9B-Claude-Mythos-5-1M-Q5_K_M.gguf"
```

> **Pro tip:** Proxy keeps running during the switch. It will return 502s for ~30-60s while llama.cpp reloads the new weights. Circuit breaker handles this gracefully.

---

### 08 — `08-download-model.ps1` — Download a GGUF

Downloads from HuggingFace (via `huggingface-cli`) or direct URL. Shows progress + verifies file size.

```powershell
# From HuggingFace
PS> D:\HermesData\scripts\ops\08-download-model.ps1 -Repo "empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF" -File "Qwythos-9B-Claude-Mythos-5-1M-Q5_K_M.gguf"

# From direct URL
PS> D:\HermesData\scripts\ops\08-download-model.ps1 -Url "https://huggingface.co/...resolve/main/model.gguf"

# Custom output directory
PS> D:\HermesData\scripts\ops\08-download-model.ps1 -Repo "empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF" -File "model.gguf" -OutputDir "K:\Phronesis-Sovereign\models"
```

**Requirements:**
- `huggingface-cli` for HuggingFace downloads: `pip install -U huggingface_hub`
- PowerShell 5+ (Windows 10+ includes)

---

## Environment

The scripts auto-detect these paths. **Edit them in each script if your layout differs:**

| Variable | Default | What it points to |
|----------|---------|-------------------|
| `LLAMA_SERVER` | `D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe` | CUDA llama.cpp binary |
| `DEFAULT_MODEL` | `D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf` | Default GGUF for backends |
| `MODELS_DIR` | `D:\PhronesisModels\models\candidates\` | Where GGUFs live |
| `PROXY_SCRIPT` | `D:\HermesData\scripts\sovereign_openai_proxy.py` | MoE gateway |
| `PYTHON` | `python` | Python interpreter |

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| `llama-server.exe` not found | Binary path wrong | Edit `$llamaServer` in `02-start-llama.ps1` |
| Proxy starts but returns 502 | Backend not ready / crashed | Run `04-status.ps1`, check if port 8090 is serving |
| CUDA out of VRAM | Model too big for ngl=99 | Lower `-Ngl` to e.g. `35` (partial offload to CPU) |
| Port already in use | Process crashed without cleanup | Run `05-stop-all.ps1`, wait 5s, then `01-recovery.ps1` |
| `python` not found in PS | MSYS bash vs PowerShell | Scripts use `Stop-Process` + `taskkill` (not `pkill`) — pure PowerShell |
| HuggingFace download fails | Missing `huggingface-cli` | `pip install -U huggingface_hub` then retry |

---

## Run Order Cheat Sheet

| Situation | Run this |
|-----------|----------|
| Everything crashed | `01-recovery.ps1` |
| Just llama.cpp died | `02-start-llama.ps1` |
| Just proxy died | `03-start-proxy.ps1` |
| Want to see what's running | `04-status.ps1` |
| Want to test the full chain | `06-smoke-test.ps1` |
| Want to swap models | `07-switch-model.ps1 -Model "..."` |
| Want to shut down for the night | `05-stop-all.ps1` |

---

*Last updated: 2026-06-29 | Author: Sovereign Agent (Phronesis Citadel)*
*Maintained at: `D:\HermesData\scripts\ops\`*
