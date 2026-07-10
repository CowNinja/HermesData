# 03-start-proxy.ps1 - Start MoE gateway proxy only (port 8091)
# Usage:  D:\HermesData\scripts\ops\03-start-proxy.ps1 [-Port 8091] [-Host 0.0.0.0]

param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port        = 8091
)

$ErrorActionPreference = "Continue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "..\Phronesis-ForkGuard.ps1")

$proxyScript = "D:\HermesData\scripts\sovereign_openai_proxy.py"

if (-not (Test-Path $proxyScript)) { Write-Host "FATAL: $proxyScript not found" -ForegroundColor Red; exit 1 }

# Port-first stop avoids WMI scans and console flashes.
$listener = Get-PortListenerPid -Port $Port
if ($listener) {
    Write-Host "  Killing existing proxy listener pid=$listener..." -ForegroundColor Cyan
    Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "  No existing proxy listener on :$Port." -ForegroundColor DarkGray
}
Start-Sleep -Seconds 1

Write-Host "Starting proxy on ${BindHost}:${Port}..." -ForegroundColor Yellow
$startScript = "D:\HermesData\scripts\Start-Sovereign-Proxy-8091.ps1"
Start-HiddenProcess -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $startScript
) | Out-Null
Start-Sleep -Seconds 3

try {
    $h = Invoke-RestMethod -Uri "http://${BindHost}:${Port}/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "Proxy is UP!" -ForegroundColor Green
    $h | ConvertTo-Json -Depth 3 | Write-Host
} catch {
    Write-Host "Proxy launched but health check pending - give it a few more seconds." -ForegroundColor DarkYellow
}

Write-Host "Proxy URL: http://${BindHost}:${Port}" -ForegroundColor Cyan