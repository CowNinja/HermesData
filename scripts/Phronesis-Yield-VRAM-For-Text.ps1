# Free VRAM for Qwythos text chat on 12GB GPUs by stopping ComfyUI on :8188.
# Pair with Phronesis-Yield-VRAM-For-Image.ps1 (stops llama for renders).
param(
    [int]$WaitSeconds = 4,
    [switch]$StartLlama,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$scriptRoot = $PSScriptRoot
$startLlamaScript = Join-Path $scriptRoot "ops\02-start-llama.ps1"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

function Get-VramFreeMb {
    $out = nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>$null
    if ($out) { return [int]($out.Trim()) }
    return 0
}

function Port-Up([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

Log "=== Yield VRAM for Text (Qwythos) ==="

$comfyPids = @(
    Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if ($comfyPids.Count -eq 0) {
    Log "ComfyUI (:8188) not listening - nothing to yield"
} else {
    foreach ($procId in $comfyPids) {
        Log "Stopping ComfyUI listener PID $procId"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds $WaitSeconds
}

$free = Get-VramFreeMb
Log "VRAM free after Comfy yield: ${free}MB"

if ($StartLlama -and -not (Port-Up 8090)) {
    if ($free -lt 9000) {
        Log "WARN: ${free}MB free may be insufficient for Qwythos 9B (~11GB)"
    }
    if (-not (Test-Path $startLlamaScript)) {
        Log "ERROR: start script missing: $startLlamaScript"
        exit 1
    }
    Log "Starting llama-server on 8090..."
    & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $startLlamaScript
    $startCode = $LASTEXITCODE
    if (($startCode -ne 0) -or -not (Port-Up 8090)) {
        Log "WARN: llama start attempt 1 failed (exit=$startCode); retrying once..."
        Start-Sleep -Seconds 3
        & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $startLlamaScript
        $startCode = $LASTEXITCODE
    }
    if (-not (Port-Up 8090)) {
        Log "ERROR: llama-server not listening on 8090 after start (exit=$startCode)"
        exit 1
    }
    Log "llama-server UP on 8090"
}

Log "=== Text yield complete ==="