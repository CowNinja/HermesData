# Start Phronesis MoE gateway - venv pythonw preferred (no console flash on Windows).
# Port 8091 - venv-owned via parent-chain marker check in ForkGuard.
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
if ($Force -and (Test-VenvOwns8091)) {
    $listener = Get-ProxyListenerPid
    if ($listener) {
        Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Write-Host "Force restart: stopped listener on 8091." -ForegroundColor Yellow
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
    -ArgumentList @($proxyPy, "--host", "0.0.0.0", "--port", "8091") `
    -WorkingDirectory $scriptDir

if (-not (Wait-ProxyVenvReady -MaxSeconds 15)) {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "FATAL: 8091 did not become venv-owned within 15s" -ForegroundColor Red
    exit 1
}

$listener = Get-ProxyListenerPid
try {
    $check = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Proxy UP (listener=$listener venv-chain=True) status=$($check.Content)" -ForegroundColor Green
} catch {
    Write-Host "FATAL: health check failed after venv bind" -ForegroundColor Red
    exit 1
}