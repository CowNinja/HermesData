# Start Phronesis MoE gateway (OpenAI-compatible protocol, local MoE only)
# Port 8091 - wires primary agent sessions to router_bridge / 808x tiers

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$proxyPy = Join-Path $scriptDir "sovereign_openai_proxy.py"
$ensurePy = Join-Path $scriptDir "ensure_hermes_sovereign_config.py"
$logDir = "D:\PhronesisVault\Operations\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Persist Hermes 64K context override before proxy boot (prevents gateway ValueError on fresh installs)
$venvPython = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "python" }
if (Test-Path $ensurePy) {
    Write-Host "Ensuring Hermes sovereign context_length >= 65536..." -ForegroundColor Cyan
    & $venvPython $ensurePy --json | Out-Null
}

# Skip restart when an existing proxy already reports GREEN/YELLOW health
try {
    $existing = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 3
    if ($existing.Content -match 'status.*(GREEN|YELLOW)') {
        Write-Host "Proxy already healthy on 8091 - skipping restart." -ForegroundColor Green
        exit 0
    }
} catch {}

# Recycle only non-venv or unhealthy listeners
$venvMarkers = @(
    "HermesData\hermes-agent\venv\Scripts\pythonw.exe",
    "HermesData\hermes-agent\venv\Scripts\python.exe"
)
$stalePids = @()
$pids = netstat -ano | Select-String ":8091\s" | Select-String "LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -Unique
foreach ($procId in $pids) {
    if ($procId -notmatch '^\d+$') { continue }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    $cmd = $proc.CommandLine
    $isVenvProxy = $false
    if ($cmd -and $cmd -match 'sovereign_openai_proxy') {
        foreach ($marker in $venvMarkers) {
            if ($cmd -match [regex]::Escape($marker)) { $isVenvProxy = $true; break }
        }
    }
    if ($isVenvProxy) { continue }
    $stalePids += $procId
}
foreach ($procId in $stalePids) {
    taskkill /F /PID $procId 2>$null | Out-Null
}
if ($stalePids.Count -gt 0) { Start-Sleep -Seconds 2 }

Write-Host "Starting phronesis-moe-gateway (sovereign_openai_proxy.py) on 8091..." -ForegroundColor Cyan
$proxyLog = Join-Path $logDir "sovereign-proxy.log"
$proxyErrLog = Join-Path $logDir "sovereign-proxy.err.log"
$pythonw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$python = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }
if (-not (Test-Path $pythonw)) { $pythonw = "pythonw" }
if (-not (Test-Path $python)) { $python = "python" }

function Start-SovereignProxyProcess {
    param([string]$Exe)
    return Start-Process -FilePath $Exe `
        -ArgumentList "`"$proxyPy`" --host 127.0.0.1 --port 8091" `
        -WorkingDirectory $scriptDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $proxyLog `
        -RedirectStandardError $proxyErrLog `
        -PassThru
}

# python.exe is primary: pythonw + stdout/stderr redirect exits after brief health (Windows quirk).
$proc = Start-SovereignProxyProcess -Exe $python
Start-Sleep -Seconds 3
$healthy = $false
try {
    $check = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 5
    $healthy = $check.Content -match 'status.*(GREEN|YELLOW)'
    if ($healthy) {
        Write-Host "Proxy UP (pid=$($proc.Id)) status=$($check.Content)" -ForegroundColor Green
    }
} catch {}

if (-not $healthy) {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "python.exe health check failed; retrying with pythonw (no log redirect)..." -ForegroundColor Yellow
    $proc = Start-Process -FilePath $pythonw `
        -ArgumentList "`"$proxyPy`" --host 127.0.0.1 --port 8091" `
        -WorkingDirectory $scriptDir `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 3
    try {
        $check = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 5
        Write-Host "Proxy UP (pid=$($proc.Id)) status=$($check.Content)" -ForegroundColor Green
    } catch {
        Write-Host "Proxy failed health check; see $proxyLog / $proxyErrLog" -ForegroundColor Red
        exit 1
    }
}