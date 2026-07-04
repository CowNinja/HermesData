# Start-Sovereign-Watchdog.ps1 - silent 60s stack watchdog (pythonw)
$ErrorActionPreference = "Stop"
$Scripts = "D:\HermesData\scripts"
$PythonW = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$Watchdog = Join-Path $Scripts "sovereign_stack_watchdog.py"

if (-not (Test-Path $PythonW)) {
    $PythonW = "pythonw"
}

Start-Process -FilePath $PythonW `
    -ArgumentList "`"$Watchdog`" --interval 60" `
    -WorkingDirectory $Scripts `
    -WindowStyle Hidden

Write-Host "Sovereign watchdog started (hidden, 60s interval)"