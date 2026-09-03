' Start-Hermes-Headless.vbs - zero-window CORE keep-alive
' Invokes pythonw sovereign_supervisor.py --ensure. No conhost.
' Supervisor boots :8090 -> :8091 -> :8642 only if a probe is down.
Option Explicit
Dim sh, fso, pyw, script
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
WScript.Sleep 15000
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
  pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
End If
script = "D:\HermesData\scripts\ops\sovereign_supervisor.py"
If fso.FileExists(pyw) And fso.FileExists(script) Then
  sh.Run """" & pyw & """ """ & script & """ --ensure", 0, False
End If
