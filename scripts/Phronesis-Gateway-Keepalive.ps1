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
            # Cadence floor for any Ensure call (anti thrash vs ops scripts).
            $ensureStamp = Join-Path $hermesRoot "state\keepalive_ensure_last.txt"
            $ensureMinSec = 300
            $mayEnsure = $true
            try {
                if (Test-Path $ensureStamp) {
                    $last = 0L
                    $raw = (Get-Content $ensureStamp -Raw -ErrorAction SilentlyContinue).Trim()
                    if ([int64]::TryParse($raw, [ref]$last)) {
                        $now = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
                        if (($now - $last) -lt $ensureMinSec) { $mayEnsure = $false }
                    }
                }
            } catch {}

            if (-not $svcAlive) {
                if ($mayEnsure) {
                    Write-Keepalive "gateway-service DEAD -> Ensure-HermesStack-Single (no Force)"
                    $ensure = Join-Path $root "Ensure-HermesStack-Single.ps1"
                    if (Test-Path $ensure) {
                        try {
                            $nowW = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
                            Set-Content -Path $ensureStamp -Value "$nowW" -Encoding ascii -NoNewline
                        } catch {}
                        & powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $ensure | Out-Null
                    } else {
                        $vbs = Join-Path $root "Start-Gateway-Service-Hidden.vbs"
                        if (Test-Path $vbs) {
                            Start-Process -FilePath "wscript.exe" -ArgumentList @("//B", $vbs) -WindowStyle Hidden | Out-Null
                        }
                    }
                } else {
                    Write-Keepalive "gateway-service DEAD but Ensure cadence hold (${ensureMinSec}s)"
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
            # Do NOT call Ensure -Force from keepalive on every blip - that
            # races Reliable/service and was a restart storm source (2026-08-02).
            # Log only; manual Ensure -Force or service outer loop handles recovery.
            if ($svcAlive -and -not $health -and -not $listen) {
                Write-Keepalive "WARN service alive but :8642 down (no Force; wait for service loop)"
            }
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
