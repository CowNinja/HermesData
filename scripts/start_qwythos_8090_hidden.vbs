' Start Qwythos llama-server with ZERO visible console (no focus steal).
' Uses pythonw + CREATE_NO_WINDOW launcher — do not call llama-server.exe from schtasks directly.
'
' Phase 3 (2026-07-25) — RTX 3060 12GB + 128GB system RAM profile:
'   - ngl=99 full GPU weights (single resident GGUF)
'   - ctx 65536 (Hermes agent floor)
'   - cache-type-k/v q8_0 (safe KV quant; frees VRAM vs f16)
'   - kv-offload on (overflow to host RAM; 128GB headroom)
'   - mmap on (weights page from disk/RAM; no mlock thrash)
'   - smaller batch/ubatch to cut prefill VRAM peaks on 12GB
' SSOT: D:\HermesData\scripts\qwythos_8090_profile.json
Option Explicit
Dim sh, pyw, launcher, llama, model, cmd
Set sh = CreateObject("WScript.Shell")
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
launcher = "D:\HermesData\scripts\launch_console_hidden.py"
llama = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"
model = "D:\PhronesisModels\models\current\Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q6_K.gguf"
cmd = """" & pyw & """ """ & launcher & """ -- """ & llama & """" & _
  " --model """ & model & """" & _
  " --host 127.0.0.1 --port 8090" & _
  " --ctx-size 65536 --n-gpu-layers 99 --parallel 1" & _
  " --cont-batching --flash-attn on --jinja" & _
  " --cache-type-k q8_0 --cache-type-v q8_0" & _
  " --kv-offload --mmap" & _
  " --batch-size 512 --ubatch-size 256"
' 0 = hidden, False = do not wait
sh.Run cmd, 0, False
