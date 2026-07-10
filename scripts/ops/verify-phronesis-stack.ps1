# verify-phronesis-stack.ps1 -- Jeff-visible stack verification (window stays open)
# Usage (recommended -- paste into an already-open PowerShell window):
#   powershell -NoProfile -File D:\HermesData\scripts\ops\verify-phronesis-stack.ps1
# Or open a persistent window:
#   powershell -NoExit -NoProfile -File D:\HermesData\scripts\ops\verify-phronesis-stack.ps1
#
# Do NOT use -WindowStyle Hidden for manual runs -- the window closes with no output.
param(
    [switch]$SkipPause,
    [switch]$RestartProxy,
    [switch]$RestartWorkspace
)

$ErrorActionPreference = "Continue"
$HermesRoot = "D:\HermesData"
$VaultRoot = "D:\PhronesisVault"
$logPath = Join-Path $HermesRoot "logs\verify-phronesis-stack.log"
$logDir = Split-Path -Parent $logPath
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log([string]$msg, [string]$color = "White") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $logPath -Value $line
    Write-Host $msg -ForegroundColor $color
}

function Test-Step([string]$label, [scriptblock]$block) {
    Write-Log "--- $label" "Cyan"
    try {
        $result = & $block
        if ($result -eq $false) {
            Write-Log "FAIL $label" "Red"
            return $false
        }
        Write-Log "PASS $label" "Green"
        return $true
    }
    catch {
        Write-Log ("FAIL $label - " + $_.Exception.Message) "Red"
        return $false
    }
}

Write-Log "Phronesis stack verification v1.3 (phase 7)" "Cyan"
Write-Log "Log: $logPath" "DarkGray"

$passed = 0
$failed = 0

if ($RestartProxy) {
    $ok = Test-Step "Restart proxy :8091" {
        & powershell -NoProfile -File (Join-Path $HermesRoot "scripts\Start-Sovereign-Proxy-8091.ps1") -Force | Out-Host
        $h = Invoke-RestMethod "http://127.0.0.1:8091/health" -TimeoutSec 10
        return ($h.status -eq "GREEN")
    }
    if ($ok) { $passed++ } else { $failed++ }
}

$step = Test-Step "FIFO admission tests (8/8)" {
    Push-Location (Join-Path $HermesRoot "scripts")
    $out = & python test_inference_admission.py 2>&1
    Pop-Location
    $out | ForEach-Object { Write-Log $_ "Gray" }
    return ($LASTEXITCODE -eq 0)
}
if ($step) { $passed++ } else { $failed++ }

$step = Test-Step "Queue comfy_yield snapshot" {
    $q = Invoke-RestMethod "http://127.0.0.1:8091/v1/queue" -TimeoutSec 10
    if (-not $q.comfy_yield) {
        Write-Log "WARN comfy_yield missing -- proxy may be stale; re-run with -RestartProxy" "Yellow"
        return $false
    }
    $cy = $q.comfy_yield | ConvertTo-Json -Compress
    Write-Log "comfy_yield: $cy" "Gray"
    return $true
}
if ($step) { $passed++ } else { $failed++ }

$step = Test-Step "Full stack health probe" {
    Push-Location (Join-Path $HermesRoot "scripts")
    $out = & python phronesis_fullstack_health.py 2>&1
    Pop-Location
    Write-Log $out "Gray"
    return ($LASTEXITCODE -eq 0)
}
if ($step) { $passed++ } else { $failed++ }

$step = Test-Step "Workspace :3001 auth-check" {
    $r = Invoke-WebRequest "http://127.0.0.1:3001/api/auth-check" -UseBasicParsing -TimeoutSec 15
    return ($r.StatusCode -eq 200)
}
if ($step) { $passed++ } else { $failed++ }

$step = Test-Step "Split GGUF verify (L04)" {
    Push-Location (Join-Path $HermesRoot "scripts")
    $out = & python verify_split_gguf.py 2>&1
    Pop-Location
    Write-Log $out "Gray"
    return ($LASTEXITCODE -eq 0)
}
if ($step) { $passed++ } else { $failed++ }

$step = Test-Step "T3 router matrix" {
    Push-Location (Join-Path $HermesRoot "scripts")
    $out = & python test_t3_router_matrix.py 2>&1
    Pop-Location
    Write-Log $out "Gray"
    return ($LASTEXITCODE -eq 0)
}
if ($step) { $passed++ } else { $failed++ }

$step = Test-Step "Comfy yield cleanup action" {
    Push-Location (Join-Path $VaultRoot "scripts")
    $out = & python warm_tier_actions.py cleanup-comfy-yield 2>&1
    Pop-Location
    Write-Log $out "Gray"
    return ($LASTEXITCODE -eq 0)
}
if ($step) { $passed++ } else { $failed++ }

if ($RestartWorkspace) {
    $ok = Test-Step "Restart workspace :3001" {
        & powershell -NoProfile -File (Join-Path $HermesRoot "scripts\ops\restart-workspace.ps1") -Build | Out-Host
        $r = Invoke-WebRequest "http://127.0.0.1:3001/api/auth-check" -UseBasicParsing -TimeoutSec 30
        return ($r.StatusCode -eq 200)
    }
    if ($ok) { $passed++ } else { $failed++ }
}

Write-Log "" "White"
Write-Log "Summary: $passed passed, $failed failed" ($(if ($failed -eq 0) { "Green" } else { "Yellow" }))
Write-Log "Dashboard: http://127.0.0.1:3001/dashboard (Ctrl+Shift+R hard refresh)" "Cyan"

if (-not $SkipPause) {
    Write-Host ""
    Write-Host "Press Enter to close this window..." -ForegroundColor DarkGray
    Read-Host | Out-Null
}

if ($failed -gt 0) { exit 1 }
exit 0