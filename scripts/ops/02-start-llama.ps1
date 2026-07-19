# 02-start-llama.ps1 - Start llama-server only (defaults from phronesis-core.json)
param(
    [string]$Model,
    [int]$Port,
    [int]$CtxSize,
    [int]$Ngl,
    [switch]$ContBatching = $true
)

$ErrorActionPreference = "Continue"
$corePath = Join-Path (Split-Path $PSScriptRoot -Parent) "phronesis-core.json"
$core = Get-Content $corePath -Raw | ConvertFrom-Json

$llamaServer = $core.llama_exe
$Model    = if ($Model) { $Model } else { $core.model }
$Port     = if ($Port) { $Port } else { [int]$core.ports.router }
if ($CtxSize) {
    # explicit param wins
} elseif ($core.use_runtime_ctx_split -and $core.runtime_ctx_size) {
    $CtxSize = [int]$core.runtime_ctx_size
} else {
    $CtxSize = [int]$core.ctx_size
}
$AdvertisedCtx = [int]$core.ctx_size
$Ngl      = if ($Ngl) { $Ngl } else { [int]$core.n_gpu_layers }

if (-not (Test-Path $llamaServer)) { Write-Host "FATAL: $llamaServer not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Model))       { Write-Host "FATAL: $Model not found" -ForegroundColor Red; exit 1 }

. (Join-Path (Split-Path $PSScriptRoot -Parent) "Phronesis-Llama-Process.ps1")
if (Stop-LlamaOnPort -Port $Port) { Start-Sleep -Seconds 1 }

# 2026-07-19: explicit --jinja for OpenAI-style tool/function calling.
# Research: llama.cpp function-calling.md — server needs jinja (default enabled on
# 2026-06-28+ builds; pin flag so a future --no-jinja default or wrapper cannot strip it).
# Hybrid-Local-Grok-Token-Policy: tool/jinja correctness is local agent IQ, not a bigger GGUF.
$args = @(
    "--model", $Model,
    "--host", "0.0.0.0",
    "--port", "$Port",
    "--ctx-size", "$CtxSize",
    "--n-gpu-layers", "$Ngl",
    "--parallel", "1",
    "--flash-attn", "on",
    "--jinja"
)
if ($ContBatching) { $args += "--cont-batching" }

# Bind 0.0.0.0 OK; health MUST use 127.0.0.1 (0.0.0.0 is not a connect target on Windows).
# Research 2026-07-19: prior ready-loop hit http://0.0.0.0:$Port → 120s false FATAL even when
# process was healthy; direct exe start to 127.0.0.1 worked. Prefer /health (fast) over /v1/models.
Write-Host "Starting llama-server on ${Port}: $(Split-Path $Model -Leaf) (runtime ctx $CtxSize, advertised $AdvertisedCtx)" -ForegroundColor Yellow
$logDir = "D:\PhronesisVault\Operations\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$outLog = Join-Path $logDir "llama-start-ps1.out.log"
$errLog = Join-Path $logDir "llama-start-ps1.err.log"
Start-Process -FilePath $llamaServer -ArgumentList $args -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$healthUrl = "http://127.0.0.1:$Port/health"
for ($i = 1; $i -le 120; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
            Write-Host "Ready after $i seconds ($healthUrl)." -ForegroundColor Green
            exit 0
        }
    } catch {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2 -ErrorAction Stop | Out-Null
            Write-Host "Ready after $i seconds (/v1/models)." -ForegroundColor Green
            exit 0
        } catch { Start-Sleep -Seconds 1 }
    }
}
Write-Host "FATAL: llama-server did not become ready on 127.0.0.1:$Port (see $errLog)" -ForegroundColor Red
exit 1