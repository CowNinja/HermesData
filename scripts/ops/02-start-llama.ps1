# 02-start-llama.ps1 - Start llama.cpp backend only (port 8090)
# Usage:  D:\HermesData\scripts\ops\02-start-llama.ps1 [-Model <path>] [-Port 8090] [-CtxSize 8192] [-Ngl 99]

param(
    [string]$Model    = "D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf",
    [int]$Port         = 8090,
    [int]$CtxSize      = 8192,
    [int]$Ngl          = 99,
    [switch]$ContBatching = $true
)

$ErrorActionPreference = "Continue"
$llamaServer = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"

if (-not (Test-Path $llamaServer)) { Write-Host "FATAL: $llamaServer not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Model))       { Write-Host "FATAL: $Model not found" -ForegroundColor Red; exit 1 }

# Kill existing llama on this port
Stop-Process -Name "llama-server" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

$args = @(
    "--model",        $Model,
    "--host",         "127.0.0.1",
    "--port",         "$Port",
    "--ctx-size",     "$CtxSize",
    "--n-gpu-layers", "$Ngl",
    "--parallel",     "1"
)
if ($ContBatching) { $args += "--cont-batching" }

Write-Host "Starting llama.cpp on port $Port with model:" -ForegroundColor Yellow
Write-Host "  $Model"
Start-Process -FilePath $llamaServer -ArgumentList $args -NoNewWindow
Write-Host "Launched. Waiting for readiness..." -ForegroundColor Green

for ($i = 1; $i -le 120; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2 -ErrorAction Stop
        if ($r.data) { Write-Host "Ready after $i seconds!" -ForegroundColor Green; exit 0 }
    } catch { Write-Host "  Waiting ($i)..."; Start-Sleep -Seconds 1 }
}
Write-Host "TIMEOUT after 120s" -ForegroundColor Red; exit 1
