# Hybrid warm mode: Qwythos + ComfyUI both resident on 12GB GPU + 128GB RAM.
# Text stays usable (reduced n_gpu_layers); Comfy uses ram_prefer (novram) staging.
# RAM hot-load: both stacks mmap/stage weights in system RAM — GPU swaps are faster than cold disk.
#
# Usage:
#   powershell -File Phronesis-Hybrid-Warm-Mode.ps1 -Mode On
#   powershell -File Phronesis-Hybrid-Warm-Mode.ps1 -Mode Off
#   powershell -File Phronesis-Hybrid-Warm-Mode.ps1 -Mode Status
param(
    [ValidateSet('On', 'Off', 'Status')]
    [string]$Mode = 'Status',
    [int]$HybridNgl = 0,
    [switch]$Quiet,
    [switch]$SkipComfyRestart
)

$ErrorActionPreference = 'Continue'
$scriptRoot = $PSScriptRoot
$hermesRoot = Split-Path $scriptRoot -Parent
$stateDir = Join-Path $hermesRoot 'state'
$corePath = Join-Path $scriptRoot 'phronesis-core.json'
$profileFile = Join-Path $stateDir 'hybrid-vram-profile.json'
$vramGuardian = Join-Path $scriptRoot 'Phronesis-VRAM-Guardian.ps1'
$startLlama = Join-Path $scriptRoot 'ops\02-start-llama.ps1'
$comfyStack = if ($env:COMFY_ROOT) {
    Join-Path $env:COMFY_ROOT 'Comfy-Stack.ps1'
} else {
    'D:\ComfyUI\Comfy-Stack.ps1'
}

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

function Get-Core {
    return Get-Content $corePath -Raw | ConvertFrom-Json
}

function Get-VramFreeMb {
    $out = nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>$null
    if ($out) { return [int]($out.Trim()) }
    return 0
}

function Port-Up([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Write-Profile([hashtable]$data) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $data | ConvertTo-Json | Set-Content -Path $profileFile -Encoding UTF8
}

function Warm-RamCaches {
    Log 'Warming RAM caches (llama + Comfy ping)...'
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:8090/v1/models' -TimeoutSec 8 | Out-Null
        Log '  llama /v1/models OK'
    } catch {
        Log "  llama warm skip: $($_.Exception.Message)"
    }
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 8 | Out-Null
        Log '  Comfy /system_stats OK'
    } catch {
        Log "  Comfy warm skip: $($_.Exception.Message)"
    }
}

function Show-Status {
    $core = Get-Core
    $hybridNgl = [int]($core.vram.hybrid_n_gpu_layers)
    if ($hybridNgl -le 0) { $hybridNgl = 38 }
    $active = $false
    $savedNgl = $null
    if (Test-Path $profileFile) {
        try {
            $p = Get-Content $profileFile -Raw | ConvertFrom-Json
            $active = [bool]$p.active
            $savedNgl = $p.hybrid_n_gpu_layers
        } catch {}
    }
    $free = Get-VramFreeMb
    $p8090 = if (Port-Up 8090) { 'UP' } else { 'DOWN' }
    $p8188 = if (Port-Up 8188) { 'UP' } else { 'DOWN' }
    $comfyMode = 'lowvram'
    $comfyModeFile = Join-Path $stateDir 'comfy-vram-mode.json'
    if (Test-Path $comfyModeFile) {
        try {
            $raw = Get-Content $comfyModeFile -Raw | ConvertFrom-Json
            $comfyMode = $raw.mode
        } catch {}
    }
    Log "Hybrid warm mode: $(if ($active) { 'ON' } else { 'OFF' })"
    Log "Qwythos n_gpu_layers: $($core.n_gpu_layers) (hybrid target: $(if ($savedNgl) { $savedNgl } else { $hybridNgl }))"
    Log "Comfy launch mode: $comfyMode"
    Log "VRAM free: ${free}MB | 8090=$p8090 8188=$p8188"
    Log 'Enable:  .\Phronesis.ps1 vram hybrid on'
    Log 'Disable: .\Phronesis.ps1 vram hybrid off'
}

switch ($Mode) {
    'Status' {
        Show-Status
        exit 0
    }
    'Off' {
        Log '=== Hybrid warm mode OFF (restore full-speed text profile) ==='
        $core = Get-Content $corePath -Raw | ConvertFrom-Json
        if (Test-Path $profileFile) {
            try {
                $p = Get-Content $profileFile -Raw | ConvertFrom-Json
                if ($p.baseline_n_gpu_layers) {
                    $core.n_gpu_layers = [int]$p.baseline_n_gpu_layers
                }
            } catch {}
        }
        $core | ConvertTo-Json -Depth 8 | Set-Content -Path $corePath -Encoding UTF8
        Write-Profile @{
            active = $false
            updated = (Get-Date).ToString('o')
            notes = 'Restored baseline n_gpu_layers; Comfy ram_prefer unchanged until ramprefer off'
        }
        if (Port-Up 8090) {
            Log 'Restarting llama with full n_gpu_layers...'
            & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $startLlama
        }
        Show-Status
        exit 0
    }
    'On' {
        Log '=== Hybrid warm mode ON (both stacks warm in RAM, shared GPU) ==='
        $core = Get-Content $corePath -Raw | ConvertFrom-Json
        $targetNgl = if ($HybridNgl -gt 0) {
            $HybridNgl
        } elseif ($core.vram.hybrid_n_gpu_layers) {
            [int]$core.vram.hybrid_n_gpu_layers
        } else {
            38
        }
        $baselineNgl = [int]$core.n_gpu_layers
        & powershell -NoProfile -ExecutionPolicy Bypass -File $vramGuardian -Mode RamPreferOn -Quiet
        $core.n_gpu_layers = $targetNgl
        $core | ConvertTo-Json -Depth 8 | Set-Content -Path $corePath -Encoding UTF8
        Write-Profile @{
            active = $true
            hybrid_n_gpu_layers = $targetNgl
            baseline_n_gpu_layers = $baselineNgl
            comfy_mode = 'ram_prefer'
            updated = (Get-Date).ToString('o')
            notes = 'Qwythos partial GPU + Comfy novram; both processes up; swaps faster than cold disk'
        }
        @{
            mode = 'hybrid'
            updated = (Get-Date).ToString('o')
        } | ConvertTo-Json | Set-Content -Path (Join-Path $stateDir 'vram-priority.json') -Encoding UTF8
        if (-not $SkipComfyRestart -and (Test-Path $comfyStack) -and (Port-Up 8188)) {
            Log 'Restarting Comfy to apply ram_prefer...'
            & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $comfyStack restart inference -Force
        } elseif (-not (Port-Up 8188) -and (Test-Path $comfyStack)) {
            Log 'Starting Comfy inference (ram_prefer)...'
            & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $comfyStack start inference
        }
        if (-not (Port-Up 8090) -and (Test-Path $startLlama)) {
            Log "Starting llama with hybrid n_gpu_layers=$targetNgl..."
            & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $startLlama
        } elseif (Port-Up 8090 -and $baselineNgl -ne $targetNgl) {
            Log "Restarting llama with hybrid n_gpu_layers=$targetNgl..."
            & powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $startLlama
        }
        Warm-RamCaches
        Show-Status
        Log 'Hybrid ON: text is slower than full VRAM but images avoid manual vram image switches.'
        exit 0
    }
}