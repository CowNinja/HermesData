# Start Phronesis MoE gateway - venv python.exe (hidden; pythonw has been exiting early on this host).
# Port 8091 - venv-owned via parent-chain marker check in ForkGuard.
# Incident/runbook: D:\PhronesisVault\Incidents\2026-07-11-sovereign-proxy-launcher-and-fallback-hardening.md
param([switch]$Force)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$proxyPy = Join-Path $scriptDir "sovereign_openai_proxy.py"
$ensurePy = Join-Path $scriptDir "ensure_hermes_sovereign_config.py"
$forkGuard = Join-Path $scriptDir "Phronesis-ForkGuard.ps1"
$venvPython = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
$venvPythonw = $venvPython -replace 'python\.exe$', 'pythonw.exe'

if (-not (Test-Path $venvPython)) {
    Write-Host "FATAL: venv python missing at $venvPython" -ForegroundColor Red
    exit 1
}

. $forkGuard

# Prefer pythonw via Start-HiddenProcess (breakaway/wscript) — no console, stays up on this host (2026-07-17).
# Fall back to python.exe if pythonw missing.
$launcher = if (Test-Path $venvPythonw) { $venvPythonw } else { $venvPython }

if (Test-Path $ensurePy) {
    Write-Host "Ensuring Hermes sovereign context_length matches phronesis-core..." -ForegroundColor Cyan
    $cfg = Invoke-HiddenProcess -FilePath $launcher -ArgumentList @($ensurePy, "--json") -WorkingDirectory $scriptDir -TimeoutMs 30000
    if ($cfg.TimedOut) {
        Write-Host "WARN: ensure_hermes_sovereign_config timed out" -ForegroundColor Yellow
    }
}

# Healthy + venv-owned (parent-chain) = skip restart unless -Force
if ((Test-VenvOwns8091) -and -not $Force) {
    Write-Host "Proxy already healthy on 8091 (venv-owned) - skipping restart." -ForegroundColor Green
    exit 0
}
if ($Force) {
    $stopped = @()
    $listener = Get-ProxyListenerPid
    if ($listener) {
        Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
        $stopped += $listener
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'sovereign_openai_proxy' } |
        ForEach-Object {
            if ($_.ProcessId -notin $stopped) {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped += $_.ProcessId
            }
        }
    Start-Sleep -Seconds 2
    Write-Host "Force restart: stopped proxy listener/processes on 8091." -ForegroundColor Yellow
}

Ensure-VenvProxyOnly | Out-Null
Start-Sleep -Seconds 1

# Clear any stale non-venv listener still holding 8091
$listener = Get-ProxyListenerPid
if ($listener -and -not (Test-ProcessVenvChain -ProcessId $listener)) {
    Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Write-Host "Starting phronesis-moe-gateway ($([IO.Path]::GetFileName($launcher))) on 8091..." -ForegroundColor Cyan
$proc = Start-HiddenProcess -FilePath $launcher `
    -ArgumentList @($proxyPy, "--host", "127.0.0.1", "--port", "8091") `
    -WorkingDirectory $scriptDir

if (-not (Wait-ProxyVenvReady -MaxSeconds 15)) {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "FATAL: 8091 did not become venv-owned within 15s" -ForegroundColor Red
    exit 1
}

# Stay-up probe: pythonw/early-exit races can pass the first health check then die.
$stable = $true
for ($i = 1; $i -le 8; $i++) {
    Start-Sleep -Seconds 1
    if (-not (Test-VenvOwns8091)) {
        $stable = $false
        break
    }
}
if (-not $stable) {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "FATAL: 8091 lost venv-owned health within 8s stability window" -ForegroundColor Red
    exit 1
}

$listener = Get-ProxyListenerPid
try {
    $check = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Proxy UP (listener=$listener venv-chain=True stable=True) status=$($check.Content)" -ForegroundColor Green
} catch {
    Write-Host "FATAL: health check failed after venv bind" -ForegroundColor Red
    exit 1
}