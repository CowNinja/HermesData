# 07-switch-model.ps1 - Swap which GGUF the llama.cpp backend serves
# Usage:  D:\HermesData\scripts\ops\07-switch-model.ps1 -Model <path> [-CtxSize 8192] [-Ngl 99]

param(
    [Parameter(Mandatory=$true)]
    [string]$Model,
    [int]$CtxSize = 8192,
    [int]$Ngl     = 99
)

$ErrorActionPreference = "Continue"
$llamaServer = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"

if (-not (Test-Path $Model))       { Write-Host "FATAL: $Model not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $llamaServer)) { Write-Host "FATAL: $llamaServer not found" -ForegroundColor Red; exit 1 }

Write-Host "Switching llama.cpp to new model..." -ForegroundColor Yellow
Write-Host "  $Model"

# Kill existing
Stop-Process -Name "llama-server" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host "  Old process killed." -ForegroundColor Cyan

# Launch new
$args = @(
    "--model",        $Model,
    "--host",         "127.0.0.1",
    "--port",         "8090",
    "--ctx-size",     "$CtxSize",
    "--n-gpu-layers", "$Ngl",
    "--parallel",     "1",
    "--cont-batching"
)
Start-Process -FilePath $llamaServer -ArgumentList $args -NoNewWindow
Write-Host "  New llama-server launched." -ForegroundColor Green

# Wait
Write-Host "Waiting for readiness..." -ForegroundColor Yellow
for ($i = 1; $i -le 120; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8090/v1/models" -TimeoutSec 2 -ErrorAction Stop
        if ($r.data) {
            Write-Host "Ready after $i seconds!" -ForegroundColor Green
            Write-Host "New model active: $($r.data[0].id)" -ForegroundColor Cyan
            exit 0
        }
    } catch { Write-Host "  Waiting ($i)..."; Start-Sleep -Seconds 1 }
}
Write-Host "TIMEOUT after 120s" -ForegroundColor Red; exit 1
