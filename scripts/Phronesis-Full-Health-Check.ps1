# Phronesis full stack health check - ports, venv, plugins, VRAM, Comfy, optional portrait.
# Usage:
#   powershell -File D:\HermesData\scripts\Phronesis-Full-Health-Check.ps1
#   powershell -File ... -PortraitTest -SkipLlamaForImage
param(
    [switch]$PortraitTest,
    [switch]$SkipLlamaForImage,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$LogDir = "D:\HermesData\logs"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $LogDir "health-check-$Stamp.log"
$HermesPy = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
$HermesExe = "D:\HermesData\hermes-agent\venv\Scripts\hermes.exe"
$Sandbox = "D:\PhronesisVault\Roleplay-Sandbox"

function Log([string]$m, [string]$color = "White") {
    $line = "$(Get-Date -Format 'HH:mm:ss') | $m"
    if (-not $Quiet) { Write-Host $line -ForegroundColor $color }
    Add-Content -Path $Log -Value $line
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Log "=== Phronesis Health Check ===" "Cyan"

$results = [ordered]@{}

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

foreach ($p in @(8090, 8091, 8642, 9119, 3001, 8188)) {
    $up = Test-Port $p
    $results["port_$p"] = if ($up) { "UP" } else { "DOWN" }
    Log ("port {0}: {1}" -f $p, $results["port_$p"]) $(if ($up) { "Green" } else { "Yellow" })
}

try {
    $vram = nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv,noheader,nounits 2>$null
    if ($vram) {
        $parts = $vram.Trim() -split ',\s*'
        $results["vram_used_mb"] = [int]$parts[0]
        $results["vram_free_mb"] = [int]$parts[1]
        $results["vram_total_mb"] = [int]$parts[2]
        Log ("VRAM: {0} MB free / {1} MB total" -f $results["vram_free_mb"], $results["vram_total_mb"]) $(if ($results["vram_free_mb"] -ge 2000) { "Green" } else { "Yellow" })
    }
} catch {
    $results["vram"] = "unknown"
    Log "VRAM: nvidia-smi unavailable" "Yellow"
}

if (Test-Path $HermesPy) {
    $importOut = & $HermesPy -c "import aiohttp, hermes_cli; print('OK')" 2>&1
    $results["venv_imports"] = if ($LASTEXITCODE -eq 0) { "OK" } else { "FAIL" }
    Log ("venv imports: {0}" -f $results["venv_imports"]) $(if ($results["venv_imports"] -eq "OK") { "Green" } else { "Red" })
} else {
    $results["venv_imports"] = "MISSING"
    Log "venv imports: MISSING python" "Red"
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 3 | Out-Null
    $results["comfyui"] = "UP"
    Log "ComfyUI: UP" "Green"
} catch {
    $results["comfyui"] = "DOWN"
    Log "ComfyUI: DOWN" "Yellow"
}

if (Test-Path $HermesExe) {
    $plain = & $HermesExe plugins list --plain 2>&1 | Out-String
    $results["comfyui_local"] = if ($plain -match 'enabled\s+user\s+1\.0\.0\s+comfyui_local') { "enabled" } else { "missing" }
    $results["plur_hermes"] = if ($plain -match 'enabled\s+user\s+[\d.]+\s+plur-hermes') { "enabled" } else { "missing" }
    Log ("plugins: comfyui_local={0} plur-hermes={1}" -f $results["comfyui_local"], $results["plur_hermes"]) "Green"
}

if ($PortraitTest) {
    if ($SkipLlamaForImage -and $results["vram_free_mb"] -lt 2000) {
        Log "PortraitTest: yielding llama for VRAM..." "Yellow"
        & (Join-Path $PSScriptRoot "Phronesis-Yield-VRAM-For-Image.ps1") -Quiet
        Start-Sleep -Seconds 3
    }
    $sidecar = Join-Path $Sandbox "sandbox\roleplay-image-sidecar.py"
    if (Test-Path $sidecar) {
        Push-Location $Sandbox
        $out = & $HermesPy $sidecar --discord-delivery `
            --user-text "OOC: portrait alice, elegant library at dusk, soft candlelight, detailed face" `
            --alice-text "She meets your gaze between the shelves." `
            --state-file runtime\continuity\STATE.md 2>&1
        Pop-Location
        $jsonLine = ($out | Where-Object { $_ -match '^\s*\{' }) | Select-Object -Last 1
        if ($jsonLine -and $jsonLine -match '"success":\s*true') {
            $results["portrait_test"] = "PASS"
            Log "PortraitTest: PASS" "Green"
        } else {
            $results["portrait_test"] = "FAIL"
            Log "PortraitTest: FAIL" "Red"
        }
    }
}

$coreOk = ($results["port_8090"] -eq "UP") -and ($results["port_8091"] -eq "UP") -and ($results["port_8642"] -eq "UP")
$results["summary"] = if ($coreOk -and $results["venv_imports"] -eq "OK") { "HEALTHY" } else { "DEGRADED" }

Log ("SUMMARY: {0}" -f $results["summary"]) $(if ($results["summary"] -eq "HEALTHY") { "Green" } else { "Yellow" })
Log "Log: $Log" "Cyan"

if ($results["summary"] -ne "HEALTHY") { exit 1 }
exit 0