# Magic Heal — one-click: full heal + hybrid warm + solo RP bridge test + health report.
param(
    [string]$Channel = "1521146755985576116",
    [string]$TestPrompt = "OOC: nude alternate portrait alice, artistic, solo, full body, highly detailed nude, bare skin, no clothing, explicit",
    [switch]$SkipTest,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$root = "D:\HermesData"
$report = Join-Path $root "logs\magic-heal-report.json"
$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"

function Log([string]$msg) {
    if (-not $Quiet) { Write-Host $msg }
}

function Port-Up([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Health-Score {
    $score = 0
    $checks = @{}
    foreach ($p in @(8090, 8642, 8188, 8189)) {
        $up = Port-Up $p
        $checks["port_$p"] = $up
        if ($up) { $score += 15 }
    }
    $hybrid = Test-Path (Join-Path $root "state\hybrid-vram-profile.json")
    if ($hybrid) {
        try {
            $prof = Get-Content (Join-Path $root "state\hybrid-vram-profile.json") -Raw | ConvertFrom-Json
            $checks.hybrid_active = [bool]$prof.active
            if ($prof.active) { $score += 10 }
        } catch {}
    }
    $lock = Join-Path $root "state\roleplay-render.lock"
    $checks.render_lock = Test-Path $lock
    if (-not (Test-Path $lock)) { $score += 10 }
    return @{ score = [Math]::Min(100, $score); checks = $checks }
}

Log "=== Magic Heal start ==="

# Dedupe Comfy main.py (keep newest listener)
$comfyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'ComfyUI\\main\.py' }
if ($comfyProcs.Count -gt 1) {
    $sorted = $comfyProcs | Sort-Object ProcessId -Descending
    $sorted | Select-Object -Skip 1 | ForEach-Object {
        Log "stop duplicate Comfy pid=$($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
}

& "$root\scripts\ops\Rp-Full-Heal.ps1" -Channel $Channel -Quiet:$Quiet
Start-Sleep -Seconds 2

& "$root\scripts\Phronesis-Hybrid-Warm-Mode.ps1" -Mode On -Quiet:$Quiet
Start-Sleep -Seconds 5

$before = Health-Score
Log "Health before test: $($before.score)/100"

$testResult = $null
if (-not $SkipTest) {
    Log "RP bridge solo test..."
    $bridge = & $py "$root\scripts\ops\rp_bridge.py" $TestPrompt --channel $Channel 2>&1
    if (-not $Quiet) { $bridge | ForEach-Object { Log $_ } }
    try {
        $line = ($bridge | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
        if ($line) { $testResult = $line | ConvertFrom-Json }
    } catch {}
}

$after = Health-Score
$latestPng = Get-ChildItem "D:\ComfyUI\output\standard__*.png" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

$reportObj = @{
    timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    channel   = $Channel
    health    = $after
    test      = $testResult
    latest_png = if ($latestPng) { $latestPng.Name } else { $null }
    latest_png_mtime = if ($latestPng) { $latestPng.LastWriteTime.ToString("s") } else { $null }
}
$reportObj | ConvertTo-Json -Depth 6 | Set-Content -Path $report -Encoding UTF8

Log "=== Magic Heal complete ==="
Log "Health: $($after.score)/100 | Latest PNG: $($reportObj.latest_png)"
if ($testResult -and $testResult.ok) {
    Log "Bridge OK: $($testResult.png)"
} elseif ($testResult) {
    Log "Bridge failed: $($testResult.error)"
}

if (-not $Quiet) {
    Write-Host ""
    Write-Host "Report: $report"
}