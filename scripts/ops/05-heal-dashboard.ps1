# 05-heal-dashboard.ps1 - restart Hermes CLI dashboard on :9119 (optional ops surface)
# Fast path: avoid full Win32_Process WMI scans (they hang 60s+ on busy hosts).
param(
    [switch]$Force
)

$ErrorActionPreference = "SilentlyContinue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "..\Phronesis-ForkGuard.ps1")

$corePath = Join-Path $scriptRoot "..\phronesis-core.json"
$dashPort = 9119
$dashHost = "127.0.0.1"
$lockFile = Join-Path $HermesRoot "state\heal-dashboard.lock"
$lockStaleSec = 180

if (Test-Path $corePath) {
    try {
        $core = Get-Content $corePath -Raw | ConvertFrom-Json
        if ($core.ports.dashboard) { $dashPort = [int]$core.ports.dashboard }
    } catch {
        # keep default
    }
}

function Test-DashboardHttp {
    param([int]$Port)
    return (Test-HttpOk -Url "http://127.0.0.1:$Port/api/status")
}

function Get-HealDashboardLockActive {
    if (-not (Test-Path $lockFile)) { return $false }
    try {
        $raw = Get-Content $lockFile -Raw
        if ($raw -match 'ts=([0-9.]+)') {
            $age = (Get-Date).ToUniversalTime().Subtract(
                [DateTimeOffset]::FromUnixTimeSeconds([int][double]$Matches[1]).UtcDateTime
            ).TotalSeconds
            if ($age -gt $lockStaleSec) {
                Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
                return $false
            }
        }
    } catch {
        Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
        return $false
    }
    return $true
}

function Set-HealDashboardLock {
    $ts = [int][double]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
    $dir = Split-Path $lockFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -Path $lockFile -Value "pid=$PID;ts=$ts" -Encoding ascii
}

function Clear-HealDashboardLock {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

if ((Get-HealDashboardLockActive) -and -not $Force) {
    Write-Host "heal-dashboard already running (lock active). Use -Force to override."
    exit 2
}

Set-HealDashboardLock
try {
    $env:HERMES_QUIET_SECRETS = '1'

    if (Test-DashboardHttp -Port $dashPort) {
        Write-Host "CLI dashboard already healthy on :$dashPort"
        exit 0
    }

    Write-Host "Healing CLI dashboard on :$dashPort ..."

    $listener = Get-PortListenerPid -Port $dashPort
    if ($listener) {
        if (-not (Test-VenvOwnsDashboard)) {
            Write-Host "Stopping non-venv listener pid=$listener on :$dashPort"
            Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        } elseif (-not (Test-DashboardHttp -Port $dashPort)) {
            Write-Host "Stale venv listener pid=$listener (HTTP down) -- restarting"
            Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }

    $agentRoot = Join-Path $HermesRoot "hermes-agent"
    $webDist = Join-Path $agentRoot "hermes_cli\web_dist\index.html"
    if (-not (Test-Path $webDist)) {
        $buildLog = Join-Path $HermesRoot "logs\dashboard-web-build.log"
        Write-Host "Building Hermes web UI (web_dist missing) -> $buildLog"
        $logDir = Split-Path $buildLog -Parent
        if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
        Add-Content -Path $buildLog -Value "=== dashboard web build $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
        Push-Location $agentRoot
        npm.cmd run build -w web *>> $buildLog
        Pop-Location
        if (-not (Test-Path $webDist)) {
            Write-Host "web_dist build FAILED -- see $buildLog" -ForegroundColor Red
            exit 1
        }
    }

    Write-Host "Starting venv dashboard..."
    Start-VenvDashboard
    $up = $false
    # Bitwarden secret hydration can take 30-60s on cold start
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-DashboardHttp -Port $dashPort) { $up = $true; break }
    }

    if (-not $up) {
        Write-Host "Fallback start (hidden pythonw)..."
        $py = if (Test-Path $VenvPythonw) { $VenvPythonw } else { $VenvPython }
        $dashArgs = @("-m", "hermes_cli.main", "dashboard", "--port", "$dashPort", "--host", $dashHost, "--no-open")
        if (Test-Path $webDist) { $dashArgs += "--skip-build" }
        Start-HiddenProcess -FilePath $py -ArgumentList $dashArgs -WorkingDirectory $agentRoot | Out-Null
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 1
            if (Test-DashboardHttp -Port $dashPort) { $up = $true; break }
        }
    }

    if ($up) {
        Write-Host "CLI dashboard listening on :$dashPort (api/status OK)"
        exit 0
    }

    Write-Host "CLI dashboard failed to bind :$dashPort within timeout"
    exit 1
} finally {
    Clear-HealDashboardLock
}