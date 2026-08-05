' Hidden proxy start — pythonw (no conhost). Solid stack 2026-08-05.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sh.CurrentDirectory = "D:\HermesData\scripts"
pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
  pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
End If
sh.Run """" & pyw & """ D:\HermesData\scripts\sovereign_openai_proxy.py --host 127.0.0.1 --port 8091", 0, False
