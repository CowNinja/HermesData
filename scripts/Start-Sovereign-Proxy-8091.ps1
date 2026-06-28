# Start Phronesis MoE gateway (OpenAI-compatible protocol, local MoE only)
# Port 8091 — wires primary agent sessions to router_bridge / 808x tiers

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$proxyPy = Join-Path $scriptDir "sovereign_openai_proxy.py"
$ensurePy = Join-Path $scriptDir "ensure_hermes_sovereign_config.py"
$logDir = "D:\PhronesisVault\Operations\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Persist Hermes 64K context override before proxy boot (prevents gateway ValueError on fresh installs)
if (Test-Path $ensurePy) {
    Write-Host "Ensuring Hermes sovereign context_length >= 65536..." -ForegroundColor Cyan
    python $ensurePy --json | Out-Null
}

# Recycle existing listener so code/config changes take effect
$pids = netstat -ano | Select-String ":8091\s" | Select-String "LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -Unique
foreach ($procId in $pids) {
    if ($procId -match '^\d+$') { taskkill /F /PID $procId 2>$null | Out-Null }
}
if ($pids) { Start-Sleep -Seconds 2 }

Write-Host "Starting phronesis-moe-gateway (sovereign_openai_proxy.py) on 8091..." -ForegroundColor Cyan
$logOut = Join-Path $logDir "sovereign-proxy-8091.log"
$logErr = Join-Path $logDir "sovereign-proxy-8091.err.log"
$proc = Start-Process -FilePath "python" `
    -ArgumentList "`"$proxyPy`" --host 127.0.0.1 --port 8091" `
    -WorkingDirectory $scriptDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError $logErr `
    -PassThru

Start-Sleep -Seconds 2
try {
    $check = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Proxy UP (pid=$($proc.Id)) status=$($check.Content)" -ForegroundColor Green
} catch {
    Write-Host "Proxy failed health check" -ForegroundColor Red
    exit 1
}
