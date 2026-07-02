# 03-start-proxy.ps1 — Start MoE gateway proxy only (port 8091)
# Usage:  D:\HermesData\scripts\ops\03-start-proxy.ps1 [-Port 8091] [-Host 127.0.0.1]

param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port        = 8091
)

$ErrorActionPreference = "Continue"
$proxyScript = "D:\HermesData\scripts\sovereign_openai_proxy.py"

if (-not (Test-Path $proxyScript)) { Write-Host "FATAL: $proxyScript not found" -ForegroundColor Red; exit 1 }

# Kill existing proxy (python processes running our proxy script) via WMI
$proxyProcs = @(
    Get-CimInstance Win32_Process -Filter "Name='python.exe' AND CommandLine LIKE '%sovereign_openai_proxy%'" -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' AND CommandLine LIKE '%sovereign_openai_proxy%'" -ErrorAction SilentlyContinue
) | Where-Object { $_ }
if ($proxyProcs) {
    Write-Host "  Killing existing proxy process(es)..." -ForegroundColor Cyan
    $proxyProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} else {
    Write-Host "  No existing proxy found." -ForegroundColor DarkGray
}
Start-Sleep -Seconds 1

Write-Host "Starting proxy on ${BindHost}:${Port}..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\Start-Sovereign-Proxy-8091.ps1"
Start-Sleep -Seconds 3

try {
    $h = Invoke-RestMethod -Uri "http://${BindHost}:${Port}/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "Proxy is UP!" -ForegroundColor Green
    $h | ConvertTo-Json -Depth 3 | Write-Host
} catch {
    Write-Host "Proxy launched but health check pending — give it a few more seconds." -ForegroundColor DarkYellow
}

Write-Host "Proxy URL: http://${BindHost}:${Port}" -ForegroundColor Cyan
