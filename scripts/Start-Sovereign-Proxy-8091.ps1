# Start Phronesis MoE gateway — venv python.exe ONLY (Session 4 hardened).
# Port 8091 — never system Python311, never pythonw fallback.

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$proxyPy = Join-Path $scriptDir "sovereign_openai_proxy.py"
$ensurePy = Join-Path $scriptDir "ensure_hermes_sovereign_config.py"
$forkGuard = Join-Path $scriptDir "Phronesis-ForkGuard.ps1"
$venvPython = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "FATAL: venv python.exe missing at $venvPython" -ForegroundColor Red
    exit 1
}

. $forkGuard

if (Test-Path $ensurePy) {
    Write-Host "Ensuring Hermes sovereign context_length >= 65536..." -ForegroundColor Cyan
    & $venvPython $ensurePy --json | Out-Null
}

# Healthy + venv-owned (parent-chain) = skip restart
if (Test-VenvOwns8091) {
    Write-Host "Proxy already healthy on 8091 (venv-owned) - skipping restart." -ForegroundColor Green
    exit 0
}

Ensure-VenvProxyOnly | Out-Null
Start-Sleep -Seconds 1

# Clear any stale non-venv listener still holding 8091
$listener = Get-ProxyListenerPid
if ($listener -and -not (Test-ProcessVenvChain -ProcessId $listener)) {
    Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Write-Host "Starting phronesis-moe-gateway (venv python.exe) on 8091..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $venvPython `
    -ArgumentList "`"$proxyPy`" --host 127.0.0.1 --port 8091" `
    -WorkingDirectory $scriptDir `
    -WindowStyle Hidden `
    -PassThru

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