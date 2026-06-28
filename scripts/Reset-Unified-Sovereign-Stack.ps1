# Reset unified sovereign stack after config pivot.
# Cycles: MoE router (8090) -> sovereign proxy (8091) -> Hermes_Gateway scheduled task.
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-PortHealth($port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Wait-PortHealth($port, [int]$maxSec = 60) {
    $deadline = (Get-Date).AddSeconds($maxSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortHealth $port) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

Write-Host "=== Unified Sovereign Stack Reset ===" -ForegroundColor Cyan

# Stop Hermes gateway scheduled task
Write-Host "Stopping Hermes_Gateway scheduled task..." -ForegroundColor Yellow
schtasks /End /TN "Hermes_Gateway" 2>$null | Out-Null
Start-Sleep -Seconds 3

# Kill stray listeners on 8090/8091 if health fails after script restarts
foreach ($port in @(8090, 8091)) {
    if (-not (Test-PortHealth $port)) {
        Write-Host "Port $port not healthy - will restart via scripts" -ForegroundColor DarkYellow
    }
}

Write-Host "Restarting unified router (8090)..." -ForegroundColor Cyan
& "$scriptDir\Start-Unified-Router-8090.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Restarting sovereign proxy (8091)..." -ForegroundColor Cyan
& "$scriptDir\Start-Sovereign-Proxy-8091.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting Hermes_Gateway scheduled task..." -ForegroundColor Cyan
schtasks /Run /TN "Hermes_Gateway" | Out-Null
Write-Host "Waiting for Hermes Gateway (8642) to become healthy..." -ForegroundColor DarkCyan
$gatewayUp = Wait-PortHealth 8642 60

$checks = @{
    "8090 MoE Router" = (Test-PortHealth 8090)
    "8091 Sovereign Proxy" = (Test-PortHealth 8091)
    "8642 Hermes Gateway" = $gatewayUp
}
foreach ($name in $checks.Keys) {
    $ok = $checks[$name]
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("  {0}: {1}" -f $name, $(if ($ok) { "UP" } else { "DOWN" })) -ForegroundColor $color
}

if ($checks.Values -contains $false) {
    Write-Host "Some services failed health check." -ForegroundColor Red
    exit 1
}
Write-Host "Stack reset complete - all services GREEN." -ForegroundColor Green
