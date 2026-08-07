# Start-Sovereign-Watchdog.ps1 - silent 60s stack watchdog (pythonw)
# Detach via start_detached.py so Grok/tool Job Objects cannot kill the loop.
$ErrorActionPreference = "Stop"
$Scripts = "D:\HermesData\scripts"
$PythonW = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$Watchdog = Join-Path $Scripts "sovereign_stack_watchdog.py"
$Detached = Join-Path $Scripts "start_detached.py"

if (-not (Test-Path $PythonW)) {
    $PythonW = "pythonw"
}

# Avoid dual watchdogs
$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'sovereign_stack_watchdog\.py' }
if ($existing) {
    Write-Host "Sovereign watchdog already running (pid=$($existing[0].ProcessId))"
    exit 0
}

if (Test-Path $Detached) {
    Start-Process -FilePath $PythonW `
        -ArgumentList @($Detached, $Watchdog, "--interval", "60") `
        -WorkingDirectory $Scripts `
        -WindowStyle Hidden | Out-Null
} else {
    Start-Process -FilePath $PythonW `
        -ArgumentList @($Watchdog, "--interval", "60") `
        -WorkingDirectory $Scripts `
        -WindowStyle Hidden | Out-Null
}

Write-Host "Sovereign watchdog started (detached, 60s interval)"