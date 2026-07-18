' Start-8090-Router.vbs - Launch llama-server in router mode (detached, hidden)
' Usage:  cscript //NoLogo Start-8090-Router.vbs
'         or just double-click to launch.

Option Explicit

Dim prebuiltDir, args, port, preSets, logDir, logOut, logErr

prebuiltDir = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13"
port = "8090"
logDir = "D:\PhronesisVault\Operations\logs"
logOut = logDir & "\llama-" & port & "-router.log"
logErr = logDir & "\llama-" & port & "-router.err.log"
preSets = "D:\PhronesisVault\Operations\models-8090.ini"

' models-max MUST be on CLI (community: ini models-max is ignored / broken)
' Do NOT pass global --ctx-size here — it overrides per-model ctx in the preset
args = """" & prebuiltDir & "\llama-server.exe"" " & _
       "--port " & port & " " & _
       "--host 127.0.0.1 " & _
       "--models-preset """ & preSets & """ " & _
       "--models-max 1 " & _
       "--models-autoload " & _
       "--flash-attn on " & _
       "--cache-type-k q8_0 " & _
       "--cache-type-v q4_0"

Dim fso, logFolder
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logFolder)

Dim ts
Set ts = fso.OpenTextFile(logOut, 8, True)
ts.WriteLine "[" & Now & "] [ROUTER] Starting llama-server in router mode on port " & port
ts.WriteLine "[" & Now & "] [ROUTER] Binary: " & prebuiltDir & "\llama-server.exe"
ts.WriteLine "[" & Now & "] [ROUTER] Presets: " & preSets
ts.WriteLine "[" & Now & "] [ROUTER] Args: " & args
ts.Close

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run args, 0, False

' Wait briefly for port to bind, then log status
WScript.Sleep 8000

Dim xhr
Set xhr = CreateObject("MSXML2.XMLHTTP")
xhr.Open "GET", "http://127.0.0.1:" & port & "/health", False
On Error Resume Next
xhr.Send
If Err.Number = 0 And xhr.Status = 200 Then
    Set ts = fso.OpenTextFile(logOut, 8, True)
    ts.WriteLine "[" & Now & "] [ROUTER] HEALTH OK - " & xhr.responseText
    ts.Close
    WScript.Echo "Router mode started on port " & port & " - HEALTH: " & xhr.responseText
Else
    Set ts = fso.OpenTextFile(logOut, 8, True)
    ts.WriteLine "[" & Now & "] [ROUTER] Health check FAILED - check " & logErr
    ts.Close
    WScript.Echo "Router mode started on port " & port & " but health check pending. Check " & logErr
End If
On Error GoTo 0
