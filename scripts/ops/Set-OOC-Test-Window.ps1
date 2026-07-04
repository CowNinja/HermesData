# One-shot: lock Discord test window + start gateway if down (never restart).
$ErrorActionPreference = "Continue"
$scriptRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $scriptRoot "Phronesis-Maintenance-Lock.ps1")
. (Join-Path $scriptRoot "Phronesis-ForkGuard.ps1")

Set-PhronesisMaintenanceLock `
    -Minutes 12 `
    -Reason "OOC discord test window" `
    -ThreadId "1521146755985576116" `
    -ProtectGateway `
    -ProtectVram

$gwListening = [bool](Get-NetTCPConnection -LocalPort 8642 -State Listen -ErrorAction SilentlyContinue)
if (-not $gwListening) {
    Write-Host "Gateway down - starting (not restarting)..."
    Set-HermesGatewayEnv
    Start-VenvGateway
} else {
    Write-Host "Gateway already listening - leaving untouched (maintenance lock active)."
}

if (Wait-GatewayReady -MaxSeconds 45) {
    Write-Host "Gateway ready on 8642"
    exit 0
}
Write-Host "Gateway not ready within timeout"
exit 1