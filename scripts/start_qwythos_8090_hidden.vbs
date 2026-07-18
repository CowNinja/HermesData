' Start Qwythos llama-server with ZERO visible console (no focus steal).
' Uses pythonw + CREATE_NO_WINDOW launcher — do not call llama-server.exe from schtasks directly.
Option Explicit
Dim sh, pyw, launcher, llama, model, cmd
Set sh = CreateObject("WScript.Shell")
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
launcher = "D:\HermesData\scripts\launch_console_hidden.py"
llama = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"
model = "D:\PhronesisModels\models\current\Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q6_K.gguf"
cmd = """" & pyw & """ """ & launcher & """ -- """ & llama & """" & _
  " --model """ & model & """" & _
  " --host 127.0.0.1 --port 8090 --ctx-size 65536 --n-gpu-layers 99" & _
  " --parallel 1 --cont-batching --flash-attn on --jinja"
' 0 = hidden, False = do not wait
sh.Run cmd, 0, False
