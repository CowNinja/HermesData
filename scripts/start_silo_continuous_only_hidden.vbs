' Continuous silo — fully hidden (pythonw + launch_console_hidden, window style 0).
' Prefer pythonw for the worker so children do not allocate console windows.
Option Explicit
Dim sh, fso, pyw, launcher, py, script
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
launcher = "D:\HermesData\scripts\launch_console_hidden.py"
py = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
If Not fso.FileExists(py) Then
  py = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
End If
script = "D:\HermesData\scripts\silo_continuous_loop.py"
' Style 0 = hidden; pythonw launcher has no console
sh.Run """" & pyw & """ """ & launcher & """ -- """ & py & """ """ & script & """ --max-cycles 0 --force-mode aggressive", 0, False
