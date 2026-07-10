#!/bin/bash
# Safe pinned restart for Qwythos + Comfy co-existence
# --mlock keeps weights in system RAM for fast VRAM loads
# Reduced n-gpu-layers leaves headroom for Comfy (lowvram)
# --parallel 4 + --cont-batching for better concurrency (from llama.cpp research)

echo "[$(date)] Stopping existing llama processes..."
taskkill //F //IM llama-server.exe 2>/dev/null || true
sleep 3

BINARY="D:/PhronesisModels/binaries/b9850/cuda12/llama-server.exe"
MODEL="D:/PhronesisModels/models/current/Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q6_K.gguf"

if [ ! -f "$BINARY" ]; then
  echo "ERROR: Binary not found at $BINARY"
  exit 1
fi
if [ ! -f "$MODEL" ]; then
  echo "ERROR: Model not found at $MODEL"
  exit 1
fi

echo "[$(date)] Starting llama-server with mlock + partial GPU layers + parallel..."
"$BINARY" \
  --model "$MODEL" \
  --port 8090 \
  --host 127.0.0.1 \
  --n-gpu-layers 28 \
  --mlock \
  --ctx-size 32768 \
  --parallel 4 \
  --cont-batching \
  > D:/HermesData/logs/llama_pinned_8090.log 2>&1 &

LLAMA_PID=$!
echo "llama-server started, PID: $LLAMA_PID"
echo "Log: D:/HermesData/logs/llama_pinned_8090.log"

sleep 10
netstat -ano | grep 8090 | grep LISTENING | head -1 || echo "8090 not yet listening (may take longer)"
echo "Current VRAM after start:"
nvidia-smi --query-gpu=memory.used --format=csv,noheader

chmod +x D:/HermesData/scripts/restart_sovereign_pinned.sh
echo "Script updated with --parallel 4 + --cont-batching (research-backed for concurrency without --batch which caused arg error)."