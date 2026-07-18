' Detached Hermes gateway supervisor (pythonw) — survives parent shells.
Option Explicit
Dim sh, pyw, script
Set sh = CreateObject("WScript.Shell")
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
script = "D:\HermesData\scripts\hermes_gateway_supervisor.py"
sh.CurrentDirectory = "D:\HermesData"
sh.Run """" & pyw & """ """ & script & """", 0, False
