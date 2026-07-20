# hermes_gateway_watchdog.ps1 (v7 - 2026-07-17)
# Canonical path expected by scheduled task Hermes_Gateway_Watchdog.
# Matches modern Windows gateway argv: `-m gateway.run` AND `hermes_cli.main gateway run`.
#
# Root-cause lessons (2026-07-17 Discord silence):
#   1. Gateway process can die silently mid/post heavy Discord tool turns (no exit-diag).
#   2. Legacy v6 only matched hermes_cli.main - missed live `-m gateway.run` processes.
#   3. Task pointed here while file lived only under archive/ - recovery never ran.
#   4. Never kill a healthy single listener. Clear dead pid/lock only.
#
# Modes:
#   default / -Loop     continuous check (IntervalSec)
#   -Once               single check + optional restore (for schtasks one-shots)

param(
    [switch]$Once,
    [switch]$Loop,
    [int]$IntervalSec = 45
)

$ErrorActionPreference = "Continue"
# This file lives in scripts\ops\ -> parent is scripts\
$scripts = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { "D:\HermesData\scripts" }
if (-not (Test-Path (Join-Path $scripts "Phronesis-ForkGuard.ps1"))) {
    $scripts = "D:\HermesData\scripts"
}
$log = "D:\HermesData\logs\hermes_gateway_watchdog.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Log([string]$m) {
    $line = "$((Get-Date).ToString('s')) $m"
    try { Add-Content -LiteralPath $log -Value $line } catch {}
}

. (Join-Path $scripts "Phronesis-ForkGuard.ps1")
. (Join-Path $scripts "Phronesis-Maintenance-Lock.ps1")

function Invoke-GatewayWatchOnce {
    $block = Test-PhronesisMaintenanceBlocked -Action gateway_heal
    if ($block.blocked) {
        Log "SKIP maintenance=$($block.reason)"
        return 0
    }

    $port = Get-GatewayPort
    $listenPid = Get-PortListenerPid -Port $port
    $health = $false
    try { $health = [bool](Test-GatewayHealth) } catch { $health = $false }

    # 2026-07-20 permanent: NEVER clear markers or DEDUP while healthy.
    # Prior thrash: Clear-Stale + DEDUP killed parent/child re-exec tree mid-turn
    # (Discord silence; turns not redelivered). Heal only when truly DOWN.
    if ($listenPid -and $health) {
        $gwCount = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.CommandLine -and (
                        $_.CommandLine -match 'hermes_cli\.main.*gateway' -or
                        $_.CommandLine -match 'gateway\.run' -or
                        $_.CommandLine -match 'hermes-agent[\\/]gateway[\\/]run\.py'
                    )
                }
        ).Count
        # Parent+child re-exec is normal (1 listener, 2 role procs). Only log.
        if ($gwCount -gt 2) {
            Log "WARN multi_role_procs=$gwCount listener=$listenPid health=1 (no kill; observe)"
        }
        Log "OK port=$port listener=$listenPid gw_procs=$gwCount health=1 no_touch=1"
        return 0
    }

    # DOWN path only: clear dead markers, then restore
    $cleared = @(Clear-StaleGatewayMarkers)
    if ($cleared.Count -gt 0) {
        Log "cleared_stale count=$($cleared.Count)"
    }

    $listenPid = Get-PortListenerPid -Port $port
    $health = $false
    try { $health = [bool](Test-GatewayHealth) } catch { $health = $false }
    $gw = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and (
                    $_.CommandLine -match 'hermes_cli\.main.*gateway' -or
                    $_.CommandLine -match 'gateway\.run' -or
                    $_.CommandLine -match 'hermes-agent[\\/]gateway[\\/]run\.py'
                )
            }
    )

    if ($listenPid -and $health) {
        Log "OK port=$port listener=$listenPid gw_procs=$($gw.Count) health=1 after_clear"
        return 0
    }

    Log "DOWN port=$port listener=$listenPid health=$([int]$health) gw_procs=$($gw.Count) -> Start-VenvGateway"
    try { Start-VenvGateway } catch { Log "Start-VenvGateway ERR $($_.Exception.Message)" }
    if (Wait-GatewayReady -MaxSeconds 50) {
        Log "RECOVERED via Start-VenvGateway"
        return 0
    }
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts "Phronesis.ps1") gateway start 2>&1 | Out-Null
    } catch { Log "Phronesis ERR $($_.Exception.Message)" }
    if (Wait-GatewayReady -MaxSeconds 40) {
        Log "RECOVERED via Phronesis.ps1 gateway start"
        return 0
    }
    Log "FAIL still down after restore attempts"
    return 1
}

Log "watchdog v7 START pid=$PID once=$Once interval=$IntervalSec"

if ($Once -and -not $Loop) {
    $code = Invoke-GatewayWatchOnce
    exit $code
}

# Continuous (default when neither -Once nor when task wants a daemon)
while ($true) {
    try {
        Invoke-GatewayWatchOnce | Out-Null
    } catch {
        Log "LOOP_ERR $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSec
}
