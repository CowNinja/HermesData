' Red-style Hermes gateway service (outer restart loop). Prefer this over multi-supervisor.
' Uses start_detached.py so CREATE_BREAKAWAY_FROM_JOB survives parent Job Objects (Grok shells).
Option Explicit
Dim sh, py, det, script
Set sh = CreateObject("WScript.Shell")
py = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
det = "D:\HermesData\scripts\start_detached.py"
script = "D:\HermesData\scripts\hermes_gateway_service.py"
sh.CurrentDirectory = "D:\HermesData"
sh.Run """" & py & """ """ & det & """ """ & script & """", 0, False
