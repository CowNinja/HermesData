# Start Sovereign Stack Watchdog — 60s MoE + proxy self-heal + telemetry optimize-tick
# Runs silently (no console windows). Uses pythonw when available.
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$watchdogPy = Join-Path $scriptDir "sovereign_stack_watchdog.py"
$logDir = "D:\PhronesisVault\Operations\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Resolve-Pythonw {
    $candidates = @(
        $env:HERMES_PYTHON,
        "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe",
        "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($p in $candidates) {
        if ($p -match 'pythonw\.exe$') { return $p }
        $w = $p -replace 'python\.exe$', 'pythonw.exe'
        if (Test-Path $w) { return $w }
        return $p
    }
    return "pythonw"
}

$pythonExe = Resolve-Pythonw
$pidFile = Join-Path $logDir "sovereign-watchdog.pid"
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "Watchdog already running (pid=$oldPid)" -ForegroundColor Green
        exit 0
    }
}

Write-Host "Starting sovereign_stack_watchdog (60s tick, silent)..." -ForegroundColor Cyan
$logOut = Join-Path $logDir "sovereign-watchdog.log"
$logErr = Join-Path $logDir "sovereign-watchdog.err.log"
$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList "`"$watchdogPy`" --interval 60" `
    -WorkingDirectory $scriptDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError $logErr `
    -PassThru

$proc.Id | Set-Content $pidFile
Start-Sleep -Seconds 2

# Initial probe — also silent (no popup)
$onceOut = Join-Path $logDir "sovereign-watchdog-once.json"
Start-Process -FilePath $pythonExe `
    -ArgumentList "`"$watchdogPy`" --once" `
    -WorkingDirectory $scriptDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $onceOut `
    -RedirectStandardError $logErr `
    -Wait | Out-Null

Write-Host "Watchdog UP (pid=$($proc.Id))" -ForegroundColor Green
