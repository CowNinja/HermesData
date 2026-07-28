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
# Research: llama.cpp function-calling.md - server needs jinja (default enabled on
# 2026-06-28+ builds; pin flag so a future --no-jinja default or wrapper cannot strip it).
# Hybrid-Local-Grok-Token-Policy: tool/jinja correctness is local agent IQ, not a bigger GGUF.
#
# 2026-07-27 Phase3 SSOT (qwythos_8090_profile.json / start_qwythos_8090_hidden.vbs):
#   cache-type-k/v q8_0 + kv-offload + mmap + batch 512/ubatch 256
#   host 127.0.0.1 (local-only; health path stays 127.0.0.1)
#   Prefer Focus-Steal-safe VBS for default Qwythos path; this PS1 is recovery fallback
#   used by model_resource_manager / sovereign_preflight - must NOT undoes Phase3.
$bindHost = "127.0.0.1"
if ($core.phase3 -and $core.phase3.host) { $bindHost = [string]$core.phase3.host }
$cacheK = "q8_0"; $cacheV = "q8_0"; $batch = 512; $ubatch = 256
if ($core.phase3) {
    if ($core.phase3.cache_type_k) { $cacheK = [string]$core.phase3.cache_type_k }
    if ($core.phase3.cache_type_v) { $cacheV = [string]$core.phase3.cache_type_v }
    if ($core.phase3.batch_size) { $batch = [int]$core.phase3.batch_size }
    if ($core.phase3.ubatch_size) { $ubatch = [int]$core.phase3.ubatch_size }
}
$args = @(
    "--model", $Model,
    "--host", $bindHost,
    "--port", "$Port",
    "--ctx-size", "$CtxSize",
    "--n-gpu-layers", "$Ngl",
    "--parallel", "1",
    "--flash-attn", "on",
    "--jinja",
    "--cache-type-k", $cacheK,
    "--cache-type-v", $cacheV,
    "--kv-offload",
    "--mmap",
    "--batch-size", "$batch",
    "--ubatch-size", "$ubatch"
)
if ($ContBatching) { $args += "--cont-batching" }

# Health MUST use 127.0.0.1 (0.0.0.0 is not a connect target on Windows).
# Research 2026-07-19: prior ready-loop hit http://0.0.0.0:$Port -> 120s false FATAL even when
# process was healthy. Prefer /health (fast) over /v1/models.
Write-Host "Starting llama-server on ${Port}: $(Split-Path $Model -Leaf) (runtime ctx $CtxSize, advertised $AdvertisedCtx, Phase3 k/v=$cacheK/$cacheV batch=$batch/$ubatch)" -ForegroundColor Yellow
$logDir = "D:\PhronesisVault\Operations\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$outLog = Join-Path $logDir "llama-start-ps1.out.log"
$errLog = Join-Path $logDir "llama-start-ps1.err.log"
# Prefer hidden pythonw launcher (no focus steal) when available
$pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$hiddenLaunch = "D:\HermesData\scripts\launch_console_hidden.py"
if ((Test-Path $pyw) -and (Test-Path $hiddenLaunch)) {
    $child = @($hiddenLaunch, "--", $llamaServer) + $args
    Start-Process -FilePath $pyw -ArgumentList $child -WindowStyle Hidden | Out-Null
} else {
    Start-Process -FilePath $llamaServer -ArgumentList $args -WindowStyle Hidden `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
}

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