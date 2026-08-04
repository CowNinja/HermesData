Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\HermesData"
' Prefer Python313 (live Hermes path 2026-08); fall back to user Python311.
pyw = "C:\Program Files\Python313\pythonw.exe"
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(pyw) Then
  pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
End If
sh.Run """" & pyw & """ ""D:\HermesData\scripts\silo_continuous_loop.py"" --max-cycles 0 --force-mode aggressive", 0, False
