# Phronesis-Gateway-Keepalive.ps1 - Lightweight gateway watchdog loop.
# Complements Phronesis-Guardian (5 min full stack heal). This loop only
# ensures :8642 stays up; it never kills a healthy listener.
param(
    [int]$IntervalSec = 90
)

$ErrorActionPreference = "SilentlyContinue"
$root = if ($PSScriptRoot) { $PSScriptRoot } else { "D:\HermesData\scripts" }
$log = "D:\PhronesisVault\Operations\logs\gateway-keepalive.log"

. (Join-Path $root "Phronesis-ForkGuard.ps1")
. (Join-Path $root "Phronesis-Maintenance-Lock.ps1")

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Write-Keepalive([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    $line | Out-File -Append -FilePath $log -Encoding utf8
}

Write-Keepalive "keepalive loop started (interval=${IntervalSec}s)"

while ($true) {
    $block = Test-PhronesisMaintenanceBlocked -Action gateway_heal
    if (-not $block.blocked) {
        if ((Test-GatewayHealth) -and (Get-PortListenerPid -Port (Get-GatewayPort))) {
            Write-Keepalive "OK health=True venv=$(Test-VenvOwnsGateway)"
        } else {
            Write-Keepalive "DOWN -> Start-VenvGateway"
            Start-VenvGateway
            if (Wait-GatewayReady -MaxSeconds 45) {
                Write-Keepalive "RECOVERED venv=$(Test-VenvOwnsGateway)"
            } else {
                Write-Keepalive "RECOVER FAIL"
            }
        }
    } else {
        Write-Keepalive "SKIP ($($block.reason))"
    }
    Start-Sleep -Seconds $IntervalSec
}