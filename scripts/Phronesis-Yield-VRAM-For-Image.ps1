# Briefly stop llama-server to free VRAM for ComfyUI Pony renders on 12GB GPUs.
# Safe when gateway/rider need image generation headroom.
param(
    [int]$WaitSeconds = 5,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

Log "=== Yield VRAM for Image ==="

$llamas = @(Get-Process -Name llama-server -ErrorAction SilentlyContinue)
if ($llamas.Count -eq 0) {
    Log "llama-server not running - nothing to yield"
    exit 0
}

foreach ($p in $llamas) {
    Log "Stopping llama-server PID $($p.Id)"
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds $WaitSeconds

try {
    $vram = nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>$null
    if ($vram) { Log "VRAM free after yield: $($vram.Trim()) MB" }
} catch {}

Log "=== Yield complete ==="