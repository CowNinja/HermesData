' Start Hermes Workspace on :3001 (detached, no console flash).
' Prefer portable Node 22 (tools\node22) — system Node 24 broke vite/SSR dist.
Option Explicit
Dim sh, node22, nodeSys, node, wsDir, cmd
Set sh = CreateObject("WScript.Shell")
wsDir = "D:\HermesData\hermes-workspace"
node22 = "D:\HermesData\tools\node22\node-v22.17.0-win-x64\node.exe"
nodeSys = "D:\Program Files\nodejs\node.exe"
If CreateObject("Scripting.FileSystemObject").FileExists(node22) Then
  node = node22
Else
  node = nodeSys
End If
sh.CurrentDirectory = wsDir
' PORT=3001 matches phronesis-core.json; HOST loopback for local-only
cmd = "cmd.exe /c set PORT=3001&& set HOST=127.0.0.1&& """ & node & """ server-entry.js"
sh.Run cmd, 0, False
