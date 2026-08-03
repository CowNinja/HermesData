' Start Qwythos llama-server with ZERO visible console (no focus steal).
' Phase 3 + 128k (2026-08-03): cmd start /B survives parent exit on Windows.
' SSOT numbers: qwythos_8090_profile.json / phronesis-core.json (keep in sync).
Option Explicit
Dim sh, cmd
Set sh = CreateObject("WScript.Shell")
cmd = "D:\HermesData\scripts\start_qwythos_8090.cmd"
' 0 = hidden window, False = do not wait
sh.Run """" & cmd & """", 0, False
