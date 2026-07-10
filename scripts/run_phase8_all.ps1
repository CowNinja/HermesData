# run_phase8_all.ps1 -- Phase 8 security + T2 (network is run-network-everything.ps1)
# Modular: registry at config/phase8_modules.yaml
param(
    [switch]$SkipPause,
    [switch]$SkipHeal
)

$ErrorActionPreference = "Continue"
$HermesRoot = "D:\HermesData"
$ScriptsDir = Join-Path $HermesRoot "scripts"
$logPath = Join-Path $HermesRoot "logs\phase8-run.log"

function Write-Log([string]$msg, [string]$color = "White") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $logPath -Value $line
    Write-Host $msg -ForegroundColor $color
}

Write-Log "Phase 8 modular sequence (8c + 8a; 8b via run-network-everything)" "Cyan"
Write-Log "Log: $logPath" "DarkGray"

if (-not $SkipHeal) {
    Write-Log "--- Heal dashboards" "Cyan"
    & powershell -NoProfile -File (Join-Path $HermesRoot "scripts\ops\heal-all-dashboards.ps1") -Quiet
}

Push-Location $ScriptsDir
$registryJson = & python modular_registry.py 2>&1
Pop-Location
Write-Log "Registry: $registryJson" "DarkGray"

$steps = @(
    @{ Name = "8c security_audit_home"; Script = "security_audit_home.py"; Args = @() },
    @{ Name = "8a fleet_sfw_gate smoke"; Script = "fleet_sfw_gate.py"; Args = @("landscape mountain sunset") },
    @{ Name = "8a fleet_image_offload gate"; Script = "fleet_image_offload.py"; Args = @("landscape mountain sunset") }
)

$passed = 0
$failed = 0
foreach ($step in $steps) {
    Write-Log ("--- " + $step.Name) "Cyan"
    Push-Location $ScriptsDir
    $out = & python $step.Script @($step.Args) 2>&1
    Pop-Location
    $out | ForEach-Object { Write-Log $_ "Gray" }
    if ($LASTEXITCODE -eq 0) {
        Write-Log ("PASS " + $step.Name) "Green"
        $passed++
    } else {
        Write-Log ("FAIL " + $step.Name) "Red"
        $failed++
    }
}

Write-Log "Phase 8 summary: $passed passed, $failed failed" ($(if ($failed -eq 0) { "Green" } else { "Yellow" }))

if (-not $SkipPause) {
    Write-Host ""
    Write-Host "Press Enter to close..." -ForegroundColor DarkGray
    Read-Host | Out-Null
}

if ($failed -gt 0) { exit 1 }
exit 0