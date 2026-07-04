# Magic Heal - one-click: full heal + hybrid warm + solo RP bridge test + health report.
param(
    [string]$Channel = "1521146755985576116",
    [string]$TestPrompt = "OOC: nude alternate portrait alice, artistic, solo, full body, highly detailed nude, bare skin, no clothing, explicit",
    [switch]$SkipTest = $true,
    [switch]$RunTest,
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

& "$root\scripts\ops\Repair-ComfyInference.ps1" -Quiet:$Quiet | Out-Null

& "$root\scripts\ops\Rp-Full-Heal.ps1" -Channel $Channel -Quiet:$Quiet
Start-Sleep -Seconds 2

& "$root\scripts\ops\Ensure-RP-Watchers.ps1" -Channel $Channel -Quiet:$Quiet

if (Test-Path "$root\scripts\ops\rp_bottleneck_scanner.py") {
    $scanOut = & $py "$root\scripts\ops\rp_bottleneck_scanner.py" --fix --channel $Channel --json-only 2>&1
    try {
        $scanLine = ($scanOut | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
        if ($scanLine) { $script:scanReport = $scanLine | ConvertFrom-Json }
    } catch {}
}

& "$root\scripts\Phronesis-Hybrid-Warm-Mode.ps1" -Mode On -Quiet:$Quiet
Start-Sleep -Seconds 5

$before = Health-Score
Log "Health before test: $($before.score)/100"

$testResult = $null
if ($RunTest -or -not $SkipTest) {
    Log "RP bridge solo test..."
    $bridge = & $py "$root\scripts\ops\rp_bridge.py" $TestPrompt --channel $Channel 2>&1
    if (-not $Quiet) { $bridge | ForEach-Object { Log $_ } }
    try {
        $line = ($bridge | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
        if ($line) { $testResult = $line | ConvertFrom-Json }
    } catch {}
}

$after = Health-Score

# Internal simulator (parse canaries, no Discord) - dry validation before live bridge test
$simReport = $null
if (Test-Path "$root\scripts\ops\rp_simulator.py") {
    $simOut = & $py "$root\scripts\ops\rp_simulator.py" --json-only 2>&1
    try {
        $simLine = ($simOut | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
        if ($simLine) { $simReport = $simLine | ConvertFrom-Json }
    } catch {}
}

$latestPng = Get-ChildItem "D:\ComfyUI\output\standard__*.png" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

$pipelineMetrics = $null
if (Test-Path "$root\scripts\ops\watch_comfy_pipeline.py") {
    $pipeOut = & $py "$root\scripts\ops\watch_comfy_pipeline.py" --once --json-only 2>&1
    try {
        $pipeLine = ($pipeOut | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
        if ($pipeLine) { $pipelineMetrics = $pipeLine | ConvertFrom-Json }
    } catch {}
}

$reportObj = @{
    timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    channel   = $Channel
    health    = $after
    test      = $testResult
    simulator = $simReport
    latest_png = if ($latestPng) { $latestPng.Name } else { $null }
    latest_png_mtime = if ($latestPng) { $latestPng.LastWriteTime.ToString("s") } else { $null }
    pipeline_metrics = $pipelineMetrics
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