# 07-switch-model.ps1 - Swap GGUF (blocked when model_rotation_locked in core)
param(
    [Parameter(Mandatory=$true)]
    [string]$Model,
    [int]$CtxSize,
    [int]$Ngl
)

# FM-430 2026-09-03 VRAM lock: switching GGUF loads extra weights. Hard refuse.
Write-Host "FM-430 VRAM lock: refusing model switch. CORE :8090 stays as-is." -ForegroundColor Red
exit 2
$corePath = Join-Path (Split-Path $PSScriptRoot -Parent) "phronesis-core.json"
$core = Get-Content $corePath -Raw | ConvertFrom-Json
if ($core.model_locked -or $core.model_rotation_locked) {
    Write-Warning "model_rotation_locked in phronesis-core.json - swap blocked. Current: $(Split-Path $core.model -Leaf)"
    exit 1
}

$ctx = if ($CtxSize) { $CtxSize } else { [int]$core.ctx_size }
$ngl = if ($Ngl) { $Ngl } else { [int]$core.n_gpu_layers }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "02-start-llama.ps1") -Model $Model -CtxSize $ctx -Ngl $ngl
exit $LASTEXITCODE