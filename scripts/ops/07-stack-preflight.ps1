# 07-stack-preflight.ps1 - One-shot stack health + config invariants + optional smoke
# Usage: D:\HermesData\scripts\ops\07-stack-preflight.ps1 [-Heal] [-Smoke] [-Json]
param(
    [switch]$Heal,
    [switch]$Smoke,
    [switch]$Json
)

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$venvPy = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
$results = [ordered]@{}

. (Join-Path $root "Phronesis-ForkGuard.ps1")

# 1) Port status
& (Join-Path $PSScriptRoot "04-status.ps1") | Out-String | ForEach-Object { $results["status"] = @{ ok = $true; detail = $_ } }

# 2) Heal 8091 if requested or unhealthy (-Force only when actually down)
$proxyBad = -not (Test-VenvOwns8091)
if ($Heal -or $proxyBad) {
    $launcherArgs = if ($proxyBad) { @("-Force") } else { @() }
    if ($proxyBad -and -not $Json) {
        Write-Host "8091 unhealthy - running Start-Sovereign-Proxy-8091.ps1 -Force" -ForegroundColor Yellow
    } elseif ($Heal -and -not $Json) {
        Write-Host "8091 healthy - ensuring proxy (no force restart)" -ForegroundColor DarkGray
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Start-Sovereign-Proxy-8091.ps1") @launcherArgs | Out-Null
    Start-Sleep -Seconds 2
    $results["proxy_heal"] = @{ ok = (Test-VenvOwns8091); detail = "venv_proxy=$(Test-VenvOwns8091)" }
}

# 3) Config invariants
$configOk = $true
if (Test-Path $venvPy) {
    $cfgOut = & $venvPy (Join-Path $root "validate_hermes_stack_config.py") 2>&1
    $configOk = ($LASTEXITCODE -eq 0)
    $results["config_validate"] = @{ ok = $configOk; detail = ($cfgOut -join "`n") }
    if (-not $Json) {
        if ($configOk) { Write-Host "[OK] config invariants" -ForegroundColor Green }
        else { Write-Host "[FAIL] config invariants" -ForegroundColor Red; $cfgOut | Write-Host }
    }
}

# 4) Systematic source integrity review (structure + compile + import + ops scan)
$sourceOk = $true
if (Test-Path $venvPy) {
    $srcOut = & $venvPy (Join-Path $root "stack_integrity_review.py") 2>&1
    $sourceOk = ($LASTEXITCODE -eq 0)
    $results["source_integrity"] = @{ ok = $sourceOk; detail = ($srcOut -join "`n") }
    if (-not $Json) {
        if ($sourceOk) { Write-Host "[OK] source integrity review (full)" -ForegroundColor Green }
        else { Write-Host "[FAIL] source integrity review" -ForegroundColor Red; $srcOut | Write-Host }
    }
}

# 5) Purge stale compression locks (non-destructive)
if (Test-Path $venvPy) {
    $purgeOut = & $venvPy (Join-Path $root "purge_expired_compression_locks.py") 2>&1
    $results["compression_locks"] = @{ ok = $true; detail = ($purgeOut -join "`n") }
    if (-not $Json) { Write-Host "[OK] compression locks: $purgeOut" -ForegroundColor Green }
}

# 6) Fast smoke tests
$fastOk = $true
if (Test-Path $venvPy) {
    foreach ($test in @(
        "test_stack_integrity_review.py",
        "test_stack_source_integrity_gate.py",
        "test_gateway_boot_integrity.py",
        "test_sovereign_flatten_history.py",
        "test_spending_limit_classifier.py"
    )) {
        $p = Join-Path $root $test
        if (-not (Test-Path $p)) { continue }
        & $venvPy $p 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $fastOk = $false; break }
    }
    $results["fast_smoke"] = @{ ok = $fastOk; detail = "integrity review + gate + flatten + billing" }
    if (-not $Json) {
        if ($fastOk) { Write-Host "[OK] fast smoke (integrity review + regressions)" -ForegroundColor Green }
        else { Write-Host "[FAIL] fast smoke" -ForegroundColor Red }
    }
}

# 7) Optional full sovereign inference smoke
if ($Smoke -and (Test-VenvOwns8091)) {
    $smokeOk = $false
    try {
        & (Join-Path $PSScriptRoot "06-smoke-test.ps1")
        $smokeOk = ($LASTEXITCODE -eq 0)
    } catch { $smokeOk = $false }
    $results["inference_smoke"] = @{ ok = $smokeOk; detail = "06-smoke-test.ps1" }
}

$allOk = $configOk -and $sourceOk -and $fastOk -and (Test-VenvOwns8091)
if ($Json) {
    $results | ConvertTo-Json -Depth 5
} else {
    $label = if ($allOk) { "PASS" } else { "ISSUES - see above" }
    $color = if ($allOk) { "Green" } else { "Yellow" }
    Write-Host ""
    Write-Host "Preflight: $label" -ForegroundColor $color
}
if ($allOk) { exit 0 } else { exit 1 }