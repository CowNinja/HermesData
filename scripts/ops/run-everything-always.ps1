# run-everything-always.ps1 -- top-level modular orchestrator (heal + network + phase8 + verify)
param(
    [switch]$SkipPause,
    [switch]$SkipHeal,
    [switch]$SkipNetwork,
    [switch]$SkipPhase8,
    [switch]$SkipVerify,
    [switch]$SkipWisdomKeeper
)

$ErrorActionPreference = "Continue"
$HermesRoot = "D:\HermesData"
$OpsDir = Join-Path $HermesRoot "scripts\ops"
$ScriptsDir = Join-Path $HermesRoot "scripts"
$logPath = Join-Path $HermesRoot "logs\everything-always.log"

function Write-Log([string]$msg, [string]$color = "White") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $logPath -Value $line
    Write-Host $msg -ForegroundColor $color
}

Write-Log "Everything always (modular orchestrator)" "Cyan"
Write-Log "Log: $logPath" "DarkGray"
Write-Log "Registry: D:\HermesData\config\phase8_modules.yaml" "DarkGray"
Write-Log "Network: D:\HermesData\config\network_tools.yaml" "DarkGray"

$blocks = @()
if (-not $SkipHeal) {
    $blocks += @{
        Name = "Heal dashboards"
        Cmd  = "powershell -NoProfile -File `"$(Join-Path $OpsDir 'heal-all-dashboards.ps1')`" -Quiet"
    }
}
if (-not $SkipNetwork) {
    $blocks += @{
        Name = "Network everything"
        Cmd  = "powershell -NoProfile -File `"$(Join-Path $OpsDir 'run-network-everything.ps1')`" -SkipPause"
    }
}
if (-not $SkipPhase8) {
    $blocks += @{
        Name = "Phase 8 modular (8c + 8a)"
        Cmd  = "powershell -NoProfile -File `"$(Join-Path $ScriptsDir 'run_phase8_all.ps1')`" -SkipPause -SkipHeal"
    }
}
if (-not $SkipWisdomKeeper) {
    $blocks += @{
        Name = "WisdomKeeper silo audit (8d)"
        Cmd  = "python `"$(Join-Path $ScriptsDir 'wisdomkeeper_silo_audit.py')`""
    }
    $blocks += @{
        Name = "Garden wall isolation check"
        Cmd  = "python `"$(Join-Path $ScriptsDir 'garden_wall.py')`""
    }
}
if (-not $SkipVerify) {
    $blocks += @{
        Name = "Verify Phronesis stack"
        Cmd  = "powershell -NoProfile -File `"$(Join-Path $OpsDir 'verify-phronesis-stack.ps1')`" -SkipPause"
    }
}

$passed = 0
$failed = 0
foreach ($block in $blocks) {
    Write-Log ("--- " + $block.Name) "Cyan"
    $exitCode = 0
    try {
        $out = Invoke-Expression $block.Cmd 2>&1
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
        $out | ForEach-Object { Write-Log $_ "Gray" }
    } catch {
        Write-Log $_.Exception.Message "Red"
        $exitCode = 1
    }
    if ($exitCode -eq 0) {
        Write-Log ("PASS " + $block.Name) "Green"
        $passed++
    } else {
        Write-Log ("FAIL " + $block.Name + " (exit $exitCode)") "Yellow"
        $failed++
    }
}

Write-Log "Everything always summary: $passed passed, $failed failed (verify fail is advisory)" "Cyan"
Write-Log "Outputs:" "Cyan"
Write-Log "  D:\PhronesisVault\Operations\logs\network-device-report.md" "Gray"
Write-Log "  D:\PhronesisVault\Operations\logs\security-audit-home.json" "Gray"
Write-Log "  D:\HermesData\logs\phase8-run.log" "Gray"
Write-Log "  D:\PhronesisVault\Operations\logs\wisdomkeeper-silo-audit.json" "Gray"
Write-Log "  RP sandbox: excluded from this orchestrator (garden wall)" "DarkGray"

if (-not $SkipPause) {
    Write-Host ""
    Write-Host "Press Enter to close..." -ForegroundColor DarkGray
    Read-Host | Out-Null
}

if ($failed -gt 0) { exit 1 }
exit 0