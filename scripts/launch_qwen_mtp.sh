#!/bin/bash
# Launch Qwen3.6 MoE + MTP on port 8092
# Uses b9850 binary (cuda12 variant, confirmed working on SM86)
# Model: unsloth MTP GGUF (auto-downloaded, contains MTP heads)
# Features: --spec-type draft-mtp --spec-draft-n-max 2 --flash-attn on

MODEL_PATH="/d/PhronesisModels/models/candidates/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf"
BINARY_PATH="/d/PhronesisModels/binaries/b9850/cuda12/llama-server.exe"
PORT=8092

# Verify model exists
if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: Model not found at $MODEL_PATH"
    echo "Download it first:"
    echo "  curl -L -o \"$MODEL_PATH\" \\"
    echo '    "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf"'
    exit 1
fi

echo "=== Launching Qwen3.6 MoE + MTP on port $PORT ==="
echo "Model: $MODEL_PATH"
echo ""

cd "$(dirname "$BINARY_PATH")"
exec ./llama-server.exe \
  -m "$MODEL_PATH" \
  --alias "Qwen3.6-35B-MTP" \
  --port $PORT --host 127.0.0.1 \
  -c 32768 \
  -ngl 99 \
  --fit on --fit-target 512 --fit-ctx 65536 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --flash-attn on \
  --batch-size 512 --ubatch-size 256 \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  --parallel 1 \
  --no-warmup 2>&1
