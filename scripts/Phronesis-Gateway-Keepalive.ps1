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
            # Keepalive is SECONDARY: ensure Red-style gateway-SERVICE + meta stay alive.
            # Do NOT start gateway.run here (dual-start / job-kill storms).
            $svcLock = Join-Path $hermesRoot "state\gateway-service.lock"
            $metaLock = Join-Path $hermesRoot "state\gateway-meta-watchdog.lock"
            $svcAlive = $false
            $metaAlive = $false
            if (Test-Path $svcLock) {
                try {
                    $spid = [int]((Get-Content $svcLock -Raw).Trim().Split()[0])
                    $svcAlive = [bool](Get-Process -Id $spid -ErrorAction SilentlyContinue)
                } catch {}
            }
            if (Test-Path $metaLock) {
                try {
                    $mpid = [int]((Get-Content $metaLock -Raw).Trim().Split()[0])
                    $metaAlive = [bool](Get-Process -Id $mpid -ErrorAction SilentlyContinue)
                } catch {}
            }
            if (-not $svcAlive) {
                Write-Keepalive "gateway-service DEAD -> Start-Gateway-Service-Hidden.vbs"
                $vbs = Join-Path $root "Start-Gateway-Service-Hidden.vbs"
                if (Test-Path $vbs) {
                    Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", $vbs) -WindowStyle Hidden | Out-Null
                }
            }
            if (-not $metaAlive) {
                Write-Keepalive "meta DEAD -> Start-Gateway-MetaWatchdog-Hidden.vbs"
                $mvbs = Join-Path $root "Start-Gateway-MetaWatchdog-Hidden.vbs"
                if (Test-Path $mvbs) {
                    Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", $mvbs) -WindowStyle Hidden | Out-Null
                }
            }
            $port = Get-GatewayPort
            $listen = [bool](Get-PortListenerPid -Port $port)
            $health = $false
            try { $health = [bool](Test-GatewayHealth) } catch { $health = $false }
            Write-Keepalive "OK service=$svcAlive meta=$metaAlive listen=$listen health=$health"
            try {
                $hb = Join-Path $hermesRoot "state\gateway-keepalive-heartbeat.json"
                @{ pid = $PID; ts = (Get-Date).ToString('o'); service = $svcAlive; meta = $metaAlive; health = $health } |
                    ConvertTo-Json | Set-Content -Path $hb -Encoding utf8
            } catch {}
        } catch {
            Write-Keepalive "LOOP_ERR: $($_.Exception.Message)"
        }
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
