# run-network-everything.ps1 -- native network stack (no Docker)
# Discovery -> report -> B1 VLAN -> optional SSH/Git backup
param(
    [switch]$SkipPause,
    [switch]$SkipBackup
)

$ErrorActionPreference = "Continue"
$HermesRoot = "D:\HermesData"
$ScriptsDir = Join-Path $HermesRoot "scripts"
$logPath = Join-Path $HermesRoot "logs\network-everything.log"

function Write-Log([string]$msg, [string]$color = "White") {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $logPath -Value $line
    Write-Host $msg -ForegroundColor $color
}

Write-Log "Network everything (native-first, no Docker)" "Cyan"
Write-Log "Log: $logPath" "DarkGray"

$steps = @(
    @{ Name = "8b native audit"; Script = "home_network_audit.py" },
    @{ Name = "SKYnet distill + labels"; Script = "skynet_distill.py" },
    @{ Name = "device report MD"; Script = "network_device_report.py" },
    @{ Name = "B1 VLAN recommendations"; Script = "network_vlan_b1.py" },
    @{ Name = "credential status"; Script = "network_cred_loader.py" }
)
# SSH backup gated by network_tools.yaml backup.ssh_enabled (default off when sealed)
if (-not $SkipBackup) {
    $steps += @{ Name = "SSH git backup"; Script = "network_backup_git.py" }
}

$passed = 0
$failed = 0
foreach ($step in $steps) {
    Write-Log ("--- " + $step.Name) "Cyan"
    Push-Location $ScriptsDir
    $out = & python $step.Script 2>&1
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

Write-Log "Reports:" "Cyan"
Write-Log "  D:\PhronesisVault\Operations\logs\network-device-report.md" "Gray"
Write-Log "  D:\PhronesisVault\Operations\logs\network-vlan-b1.json" "Gray"
Write-Log "  D:\PhronesisVault\Operations\logs\network-devices.json" "Gray"

Write-Log "Summary: $passed passed, $failed failed" ($(if ($failed -eq 0) { "Green" } else { "Yellow" }))

if (-not $SkipPause) {
    Write-Host ""
    Write-Host "Press Enter to close..." -ForegroundColor DarkGray
    Read-Host | Out-Null
}

if ($failed -gt 0) { exit 1 }
exit 0