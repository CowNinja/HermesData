# Reset unified sovereign stack after config pivot.
# Delegates to Phronesis-OneButton-Start (8090 + 8091 + 8642 gateway).
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

& powershell -NoProfile -ExecutionPolicy Bypass -File "$scriptDir\Phronesis-OneButton-Stop.ps1"
Start-Sleep -Seconds 3

Write-Host "Starting full stack via OneButton..." -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File "$scriptDir\Phronesis-OneButton-Start.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for Hermes Gateway (8642)..." -ForegroundColor DarkCyan
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
