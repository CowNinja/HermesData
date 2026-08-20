' Start Qwythos llama-server with ZERO visible console (no focus steal).
' WMI via start_qwythos_detached.py — start /B still dies inside Grok Job Objects.
' SSOT numbers: qwythos_8090_profile.json / phronesis-core.json (keep in sync).
Option Explicit
Dim sh, pyw, starter
Set sh = CreateObject("WScript.Shell")
pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
starter = "D:\HermesData\scripts\start_qwythos_detached.py"
sh.CurrentDirectory = "D:\HermesData"
sh.Run """" & pyw & """ """ & starter & """", 0, False
