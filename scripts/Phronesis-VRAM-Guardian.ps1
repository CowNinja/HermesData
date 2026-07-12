# VRAM guardian for 12GB RTX 3060 - one GPU cannot host Qwythos + Comfy Pony together.
# Usage:
#   powershell -File Phronesis-VRAM-Guardian.ps1 -Mode Text       # !textmode - chat priority
#   powershell -File Phronesis-VRAM-Guardian.ps1 -Mode Image      # !imagefree - render priority
#   powershell -File Phronesis-VRAM-Guardian.ps1 -Mode Status
#   powershell -File Phronesis-VRAM-Guardian.ps1 -Mode RamPreferOn   # Comfy novram experiment
#   powershell -File Phronesis-VRAM-Guardian.ps1 -Mode RamPreferOff  # Comfy lowvram default
param(
    [ValidateSet('Text', 'Image', 'Status', 'RamPreferOn', 'RamPreferOff', 'RamPreferStatus')]
    [string]$Mode = 'Status',
    [switch]$Quiet,
    [switch]$RestartComfy
)

$ErrorActionPreference = "Continue"
$scriptRoot = $PSScriptRoot
$stateDir = Join-Path (Split-Path $scriptRoot -Parent) "state"
$stateFile = Join-Path $stateDir "vram-priority.json"
$comfyModeFile = Join-Path $stateDir "comfy-vram-mode.json"
$yieldText = Join-Path $scriptRoot "Phronesis-Yield-VRAM-For-Text.ps1"
$yieldImage = Join-Path $scriptRoot "Phronesis-Yield-VRAM-For-Image.ps1"
$lockScript = Join-Path $scriptRoot "Phronesis-Maintenance-Lock.ps1"
if (Test-Path $lockScript) { . $lockScript }
$comfyStack = if ($env:COMFY_ROOT) {
    Join-Path $env:COMFY_ROOT "Comfy-Stack.ps1"
} else {
    "D:\ComfyUI\Comfy-Stack.ps1"
}

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

function Write-ModeState([string]$mode, [switch]$SiloPrimary, [switch]$ClearSiloPrimary) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $keepSilo = $false
    if (Test-Path $stateFile) {
        try { $keepSilo = [bool]((Get-Content $stateFile -Raw | ConvertFrom-Json).silo_primary) } catch {}
    }
    $payload = @{
        mode    = $mode
        updated = (Get-Date).ToString("o")
    }
    if ($SiloPrimary) { $payload.silo_primary = $true }
    elseif ($keepSilo -and -not $ClearSiloPrimary -and $mode -eq 'text') { $payload.silo_primary = $true }
    elseif ($ClearSiloPrimary) { $payload.silo_primary = $false }
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($stateFile, ($payload | ConvertTo-Json -Compress), $utf8NoBom)
}

function Get-ComfyVramMode {
    if (-not (Test-Path $comfyModeFile)) { return "lowvram" }
    try {
        $raw = Get-Content $comfyModeFile -Raw | ConvertFrom-Json
        if ($raw.mode -eq "ram_prefer") { return "ram_prefer" }
    } catch {}
    return "lowvram"
}

function Set-ComfyVramMode([string]$mode) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    @{
        mode    = $mode
        updated = (Get-Date).ToString("o")
        notes   = if ($mode -eq "ram_prefer") {
            "Comfy launches with novram + disable-smart-memory (heavier RAM staging, slower renders)"
        } else {
            "Comfy launches with lowvram (default balance)"
        }
    } | ConvertTo-Json | Set-Content -Path $comfyModeFile -Encoding UTF8
}

function Restart-ComfyIfRequested {
    if (-not $RestartComfy) { return }
    if (-not (Test-Path $comfyStack)) {
        Log "WARN: Comfy-Stack not found at $comfyStack"
        return
    }
    if (-not (Port-Up 8188)) {
        Log 'Comfy not running on port 8188 - new flags apply on next start'
        return
    }
    Log "Restarting Comfy to apply new VRAM mode..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $comfyStack restart inference -Force
}

function Show-Status {
    $mode = "unknown"
    if (Test-Path $stateFile) {
        try { $mode = (Get-Content $stateFile -Raw | ConvertFrom-Json).mode } catch {}
    }
    $comfyMode = Get-ComfyVramMode
    $free = Get-VramFreeMb
    $p8090 = if (Port-Up 8090) { "UP" } else { "DOWN" }
    $p8091 = if (Port-Up 8091) { "UP" } else { "DOWN" }
    $p8188 = if (Port-Up 8188) { "UP" } else { "DOWN" }
    $llama = @(Get-Process -Name llama-server -ErrorAction SilentlyContinue).Count
    Log "VRAM priority: $mode"
    Log ('Comfy launch mode: {0} (lowvram=default, ram_prefer=novram experiment)' -f $comfyMode)
    Log ('VRAM free: {0}MB | 8090={1} 8091={2} 8188={3} | llama_count={4}' -f $free, $p8090, $p8091, $p8188, $llama)
    Log "Text mode:       .\Phronesis.ps1 vram text"
    Log "Image mode:      .\Phronesis.ps1 vram image"
    Log "RAM prefer ON:   .\Phronesis.ps1 vram ramprefer on"
    Log "RAM prefer OFF:  .\Phronesis.ps1 vram ramprefer off"
}

switch ($Mode) {
    'Status' { Show-Status; exit 0 }
    'RamPreferStatus' { Show-Status; exit 0 }
    'RamPreferOn' {
        Log "=== VRAM Guardian: Comfy RAMPrefer ON (novram mode) ==="
        Set-ComfyVramMode "ram_prefer"
        Restart-ComfyIfRequested
        Show-Status
        Log "Next Comfy start uses heavier system RAM staging. Renders may be slower."
        exit 0
    }
    'RamPreferOff' {
        Log "=== VRAM Guardian: Comfy RAMPrefer OFF (lowvram default) ==="
        Set-ComfyVramMode "lowvram"
        Restart-ComfyIfRequested
        Show-Status
        exit 0
    }
    'Text' {
        if (Get-Command Test-PhronesisMaintenanceBlocked -ErrorAction SilentlyContinue) {
            $vramBlock = Test-PhronesisMaintenanceBlocked -Action vram_switch
            if ($vramBlock.blocked) {
                Log "VRAM text blocked: $($vramBlock.reason)"
                Show-Status
                exit 2
            }
        }
        Log "=== VRAM Guardian: TEXT priority (!textmode) ==="
        $args = @('-StartLlama')
        if ($Quiet) { $args += '-Quiet' }
        & powershell -NoProfile -ExecutionPolicy Bypass -File $yieldText @args
        $pausePy = Join-Path $scriptRoot "pipeline_pause.py"
        $venvPy = (Get-Content (Join-Path $scriptRoot "phronesis-core.json") -Raw | ConvertFrom-Json).venv_python
        if (Test-Path $pausePy) { & $venvPy $pausePy pause --reason vram_text_mode | Out-Null }
        Write-ModeState 'text'
        Show-Status
        exit $LASTEXITCODE
    }
    'Image' {
        if (Get-Command Test-PhronesisMaintenanceBlocked -ErrorAction SilentlyContinue) {
            $vramBlock = Test-PhronesisMaintenanceBlocked -Action vram_switch
            if ($vramBlock.blocked) {
                Log "VRAM image blocked: $($vramBlock.reason)"
                Show-Status
                exit 2
            }
        }
        Log "=== VRAM Guardian: IMAGE priority (!imagefree) ==="
        $pausePy = Join-Path $scriptRoot "pipeline_pause.py"
        $venvPy = (Get-Content (Join-Path $scriptRoot "phronesis-core.json") -Raw | ConvertFrom-Json).venv_python
        if (Test-Path $pausePy) { & $venvPy $pausePy resume --reason vram_image_mode | Out-Null }
        $args = @()
        if ($Quiet) { $args += '-Quiet' }
        & powershell -NoProfile -ExecutionPolicy Bypass -File $yieldImage @args
        if (Test-Path $comfyStack) {
            Log "Starting ComfyUI inference via Comfy-Stack..."
            & powershell -NoProfile -ExecutionPolicy Bypass -File $comfyStack start inference
        }
        Write-ModeState 'image' -ClearSiloPrimary
        Show-Status
        exit 0
    }
}