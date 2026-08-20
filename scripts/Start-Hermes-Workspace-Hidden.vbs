' Start Hermes Workspace on :3001 (WMI-detached, no console flash).
' sh.Run from a Grok/tool shell stays in the Job — :3001 dies when the shell exits.
' Prefer portable Node 22 (tools\node22) - system Node 24 broke vite/SSR dist.
' PORT defaults to 3001 in server-entry.js.
Option Explicit
Dim fso, loc, svc, startup, node22, nodeSys, node, wsDir, cmdline, result
Set fso = CreateObject("Scripting.FileSystemObject")
wsDir = "D:\HermesData\hermes-workspace"
node22 = "D:\HermesData\tools\node22\node-v22.17.0-win-x64\node.exe"
nodeSys = "D:\Program Files\nodejs\node.exe"
If fso.FileExists(node22) Then
  node = node22
Else
  node = nodeSys
End If
cmdline = """" & node & """ server-entry.js"
Set loc = CreateObject("WbemScripting.SWbemLocator")
Set svc = loc.ConnectServer(".", "root\cimv2")
Set startup = svc.Get("Win32_ProcessStartup").SpawnInstance_
startup.ShowWindow = 0
result = svc.Get("Win32_Process").Create(cmdline, wsDir, startup)
