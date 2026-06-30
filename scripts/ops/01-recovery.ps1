# 01-recovery.ps1 — Full Stack Crash Recovery
# Kills zombies, starts llama.cpp (8090) + proxy (8091), waits for readiness.
# Usage:  D:\HermesData\scripts\ops\01-recovery.ps1

param(
    [string]$Model = "D:\PhronesisModels\models\candidates\Qwen2.5-Coder-14B-Instruct-abliterated-Q5_K_M.gguf",
    [int]$CtxSize = 8192,
    [int]$Ngl = 99
)

$ErrorActionPreference = "Continue"
$llamaServer = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"
$proxyScript  = "D:\HermesData\scripts\sovereign_openai_proxy.py"

Write-Host "`n=== PHASE 0: Kill zombies ===" -ForegroundColor Yellow
Stop-Process -Name "llama-server" -Force -ErrorAction SilentlyContinue
# Kill only our proxy python via WMI (not all python)
$zombieProxies = Get-CimInstance Win32_Process -Filter "Name='python.exe' AND CommandLine LIKE '%sovereign_openai_proxy%'" -ErrorAction SilentlyContinue
if ($zombieProxies) { $zombieProxies | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }
Start-Sleep -Seconds 2
Write-Host "Processes killed." -ForegroundColor Green

Write-Host "`n=== PHASE 1: Verifying paths ===" -ForegroundColor Yellow
if (-not (Test-Path $llamaServer)) { Write-Host "FATAL: llama-server.exe not found at $llamaServer" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $proxyScript))  { Write-Host "FATAL: proxy script not found at $proxyScript" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Model))       { Write-Host "FATAL: model not found at $Model" -ForegroundColor Red; exit 1 }
Write-Host "All paths OK." -ForegroundColor Green

Write-Host "`n=== PHASE 2: Starting llama.cpp on port 8090 ===" -ForegroundColor Yellow
$llamaArgs = @(
    "--model",        $Model,
    "--host",         "127.0.0.1",
    "--port",         "8090",
    "--ctx-size",     "$CtxSize",
    "--n-gpu-layers", "$Ngl",
    "--parallel",     "1",
    "--cont-batching"
)
Write-Host "  Command: $llamaServer $($llamaArgs -join ' ')"
Start-Process -FilePath $llamaServer -ArgumentList $llamaArgs -NoNewWindow
Write-Host "  llama-server launched." -ForegroundColor Green

Write-Host "`n=== PHASE 3: Waiting for llama.cpp readiness (max 120s) ===" -ForegroundColor Yellow
$ready = $false
for ($i = 1; $i -le 120; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8090/v1/models" -TimeoutSec 2 -ErrorAction Stop
        if ($r.data) {
            Write-Host "  llama.cpp ready after $i seconds!" -ForegroundColor Green
            $ready = $true
            break
        }
    } catch {
        Write-Host "  Waiting... ($i)"
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) { Write-Host "TIMEOUT: llama.cpp did not respond after 120s" -ForegroundColor Red; exit 1 }

Write-Host "`n=== PHASE 4: Starting proxy on port 8091 ===" -ForegroundColor Yellow
Start-Process -FilePath "python" -ArgumentList $proxyScript, "--host", "127.0.0.1", "--port", "8091" -NoNewWindow
Start-Sleep -Seconds 3
Write-Host "  Proxy launched." -ForegroundColor Green

Write-Host "`n=== PHASE 5: Health check ===" -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8091/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  Proxy health:" -ForegroundColor Cyan
    $health | ConvertTo-Json -Depth 5 | Write-Host
} catch {
    Write-Host "  Proxy health check failed — it may still be warming up." -ForegroundColor DarkYellow
}

Write-Host "`n=== RECOVERY COMPLETE ===" -ForegroundColor Green
Write-Host "  llama.cpp  -> http://127.0.0.1:8090" -ForegroundColor Cyan
Write-Host "  proxy      -> http://127.0.0.1:8091" -ForegroundColor Cyan
Write-Host ""
