# One-command stack optimize: hybrid warm + watchers + Comfy dedupe + health report.
# Inspired by community RP setups: hot RAM caches, singleton daemons, no manual switches.
param(
    [string]$Channel = "1521146755985576116",
    [switch]$SkipHybrid,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$root = "D:\HermesData"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

Log "=== Accelerate Everything ==="

& "$root\scripts\ops\Repair-ComfyInference.ps1" -Quiet:$Quiet | Out-Null

if (-not $SkipHybrid) {
    & "$root\scripts\Phronesis-Hybrid-Warm-Mode.ps1" -Mode On -Quiet:$Quiet
}

& "$root\scripts\ops\Repair-ComfyInference.ps1" -Quiet:$Quiet | Out-Null

& "$root\scripts\ops\Ensure-RP-Watchers.ps1" -Channel $Channel -Quiet:$Quiet

# Clear stale render lock when holder is not an active render
$renderLock = Join-Path $root "state\roleplay-render.lock"
if (Test-Path $renderLock) {
    $clearLock = $false
    try {
        $raw = (Get-Content $renderLock -Raw).Trim()
        $lockPid = if ($raw -match ':') { [int]($raw.Split(':')[0]) } else { [int]$raw }
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$lockPid" -ErrorAction SilentlyContinue
        if (-not $proc) {
            $clearLock = $true
        } elseif ($proc.CommandLine -notmatch 'render-roleplay-image|generate\.py') {
            $clearLock = $true
        } else {
            $ts = if ($raw -match ':') { [double]($raw.Split(':')[-1]) } else { 0 }
            $age = if ($ts) {
                (Get-Date).ToUniversalTime().Subtract((Get-Date '1970-01-01')).TotalSeconds - $ts
            } else { 0 }
            if ($age -gt 1800) { $clearLock = $true }
        }
        if ($clearLock) {
            Remove-Item $renderLock -Force
            Log "cleared stale render lock"
        }
    } catch {
        Remove-Item $renderLock -Force -ErrorAction SilentlyContinue
        Log "cleared unreadable render lock"
    }
}

& "$root\scripts\ops\WisdomVault-Health.ps1" -Quiet:$Quiet

$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"
if (Test-Path $py) {
    & $py "$root\scripts\ops\rp_simulator.py" 2>&1 | ForEach-Object { if (-not $Quiet) { Log $_ } }
}

Log "=== Accelerate complete ==="