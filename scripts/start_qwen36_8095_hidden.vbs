Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13"
cmd = """D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe""" & _
 " --model ""D:\PhronesisModels\models\qwen36-35b-a3b-abliterated\Huihui-Qwen3.6-35B-A3B-abliterated.Q4_K_S.gguf""" & _
 " --host 127.0.0.1 --port 8095 --ctx-size 32768 --n-gpu-layers 99 --n-cpu-moe 26" & _
 " --parallel 1 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 -b 2048 -ub 1024 --cont-batching"
sh.Run cmd, 0, False
