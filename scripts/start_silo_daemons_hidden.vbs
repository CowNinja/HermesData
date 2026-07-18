' Launch continuous + sprint with CREATE_NO_WINDOW (no focus steal).
' Respect STOP files — overnight/travel should also check those.
Option Explicit
Dim fso, sh, pyw, launcher, py, root
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = "D:\HermesData"
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
launcher = "D:\HermesData\scripts\launch_console_hidden.py"
py = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
If fso.FileExists(root & "\state\silo_continuous.STOP") = False Then
  sh.Run """" & pyw & """ """ & launcher & """ -- """ & py & """ """ & root & "\scripts\silo_continuous_loop.py"" --max-cycles 0 --force-mode aggressive", 0, False
End If
If fso.FileExists(root & "\state\silo_autonomous.STOP") = False Then
  ' Overnight default 8h depth cook (2026-07-18 Jeff sleep cook)
  sh.Run """" & pyw & """ """ & launcher & """ -- """ & py & """ """ & root & "\scripts\silo_autonomous_sprint.py"" --hours 8 --sleep 25 --smoke", 0, False
End If
