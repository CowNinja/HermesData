# Phronesis-Gateway-Keepalive.ps1 - Durable :8642 Discord gateway watchdog loop.
# Complements Phronesis-Guardian (5 min full stack heal) and stack_healing_once (30m).
# Policy: never kill a healthy listener; clear stale markers; always try/catch so one
# failure cannot end the loop (root cause of prior "keepalive died after one tick").
param(
    [int]$IntervalSec = 60
)

$ErrorActionPreference = "Continue"
$root = if ($PSScriptRoot) { $PSScriptRoot } else { "D:\HermesData\scripts" }
$log = "D:\PhronesisVault\Operations\logs\gateway-keepalive.log"
$hermesRoot = "D:\HermesData"

. (Join-Path $root "Phronesis-ForkGuard.ps1")
. (Join-Path $root "Phronesis-Maintenance-Lock.ps1")

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $hermesRoot "logs") | Out-Null

function Write-Keepalive([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    try { $line | Out-File -Append -FilePath $log -Encoding utf8 } catch {}
    try {
        $line | Out-File -Append -FilePath (Join-Path $hermesRoot "logs\gateway-keepalive.log") -Encoding utf8
    } catch {}
}

# Single-instance: if another keepalive holds the lock with a live PID, exit.
$kaLock = Join-Path $hermesRoot "state\gateway-keepalive.lock"
New-Item -ItemType Directory -Force -Path (Split-Path $kaLock) | Out-Null
if (Test-Path $kaLock) {
    try {
        $old = [int]((Get-Content $kaLock -Raw).Trim().Split()[0])
        if ($old -gt 0 -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
            Write-Keepalive "exit: another keepalive alive pid=$old"
            exit 0
        }
    } catch {}
}
Set-Content -Path $kaLock -Value "$PID $(Get-Date -Format o)" -NoNewline

Write-Keepalive "keepalive loop started (interval=${IntervalSec}s) pid=$PID"

try {
    while ($true) {
        try {
            $port = Get-GatewayPort
            $listen = [bool](Get-PortListenerPid -Port $port)
            $health = $false
            try { $health = [bool](Test-GatewayHealth) } catch { $health = $false }

            # HARD RULE: if port is down, always attempt restore. Never SKIP for
            # discord_turn_in_flight when there is nothing listening (silent crash case).
            $block = $null
            if ($listen) {
                $block = Test-PhronesisMaintenanceBlocked -Action gateway_heal
            } else {
                $block = @{ blocked = $false; reason = "port_down_force_heal" }
            }

            if ($block.blocked) {
                Write-Keepalive "SKIP ($($block.reason)) listen=$listen health=$health"
            } else {
                $cleared = @(Clear-StaleGatewayMarkers)
                if ($cleared.Count -gt 0) {
                    Write-Keepalive "cleared_stale markers=$($cleared.Count)"
                }
                $venv = $false
                try { $venv = [bool](Test-VenvOwnsGateway) } catch { $venv = $false }

                if ($listen -and $health) {
                    Write-Keepalive "OK health=True listen=True venv=$venv"
                    # Heartbeat for Guardian/Heal to detect live keepalive
                    try {
                        $hb = Join-Path $hermesRoot "state\gateway-keepalive-heartbeat.json"
                        @{ pid = $PID; ts = (Get-Date).ToString('o'); ok = $true } | ConvertTo-Json |
                            Set-Content -Path $hb -Encoding utf8
                    } catch {}
                } else {
                    Write-Keepalive "DOWN listen=$listen health=$health venv=$venv reason=$($block.reason) -> Start-VenvGateway"
                    try {
                        Start-VenvGateway
                    } catch {
                        Write-Keepalive "Start-VenvGateway ERR: $($_.Exception.Message)"
                    }
                    $ready = $false
                    try { $ready = Wait-GatewayReady -MaxSeconds 50 } catch { $ready = $false }
                    if ($ready) {
                        Write-Keepalive "RECOVERED venv=$(Test-VenvOwnsGateway)"
                    } else {
                        try {
                            # Hidden: never flash a second console from keepalive recover path
                            & powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis.ps1") gateway start 2>&1 | Out-Null
                        } catch {
                            Write-Keepalive "Phronesis start ERR: $($_.Exception.Message)"
                        }
                        try { $ready = Wait-GatewayReady -MaxSeconds 40 } catch { $ready = $false }
                        if ($ready) {
                            Write-Keepalive "RECOVERED_via_phronesis"
                        } else {
                            Write-Keepalive "RECOVER FAIL listen=$([bool](Get-PortListenerPid -Port $port)) health=$(Test-GatewayHealth)"
                        }
                    }
                }
            }
        } catch {
            Write-Keepalive "LOOP_ERR: $($_.Exception.Message)"
        }
        # Refresh lock heartbeat
        try { Set-Content -Path $kaLock -Value "$PID $(Get-Date -Format o)" -NoNewline } catch {}
        Start-Sleep -Seconds $IntervalSec
    }
} finally {
    try {
        if (Test-Path $kaLock) {
            $cur = Get-Content $kaLock -Raw -ErrorAction SilentlyContinue
            if ($cur -and $cur.StartsWith("$PID")) { Remove-Item $kaLock -Force -ErrorAction SilentlyContinue }
        }
    } catch {}
    Write-Keepalive "keepalive loop exit pid=$PID"
}
