# Safe Hermes update - ONE apply door (Jeff-armed).
# Measure first: python D:\HermesData\scripts\ops\hermes_update_once.py status
# Preflight refuses unmerged / diverged / extra house voice files.
# Then: unload house overlays, quiet kitchen, hermes update, re-layer, Ensure
# (not SAT --heal). SAT --status-only at the end.
#
# Use this instead of the Desktop Update button while the kitchen is live.
# Desktop preflight treats service/meta/proxy/dashboard as venv blockers.
# Apply bounces 8642/8091/8090 and resets OS-1 that UTC day.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\HermesData\scripts\Phronesis-Safe-Hermes-Update.ps1
#   ... -ExportOnly     snapshot house code, do not update
#   ... -NoReapply      stay vanilla after update (house code stays in house-overlays)
#   ... -NoBackup       pass --no-backup to hermes update
#   ... -Force          pass --force to hermes update (shim guard only)
#   ... -DryRun         export + status only
#   ... -Resume         skip export+unload (tree already vanilla; keep overlay)
#
# ASCII-only. Windows PowerShell 5.1 breaks on em-dashes in UTF-8 without BOM.
# Native stderr (Bitwarden, pip) must NOT abort: EAP=Continue around hermes.exe.
param(
    [switch]$Force,
    [switch]$NoBackup,
    [switch]$NoReapply,
    [switch]$ExportOnly,
    [switch]$DryRun,
    [switch]$Resume
)

$ErrorActionPreference = "Continue"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$HermesRoot = "D:\HermesData"
$Agent = Join-Path $HermesRoot "hermes-agent"
$State = Join-Path $HermesRoot "state"
$LogDir = Join-Path $HermesRoot "logs"
$Py = Join-Path $Agent "venv\Scripts\python.exe"
$HermesExe = Join-Path $Agent "venv\Scripts\hermes.exe"
$Overlay = Join-Path $HermesRoot "scripts\ops\hermes_house_overlay.py"
$UpdateDoor = Join-Path $HermesRoot "scripts\ops\hermes_update_once.py"
$Quiet = Join-Path $HermesRoot "scripts\Quiet-HermesStack-For-Update.ps1"
$Ensure = Join-Path $HermesRoot "scripts\Ensure-HermesStack-Single.ps1"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $LogDir "safe-update-$Stamp.log"

New-Item -ItemType Directory -Force -Path $State, $LogDir | Out-Null

function Write-Safe([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    try { Add-Content -Path $Log -Value $line -Encoding ascii } catch {}
    Write-Host $line
}

function Invoke-Overlay([string]$action) {
    if (-not (Test-Path $Py)) {
        throw "venv python missing: $Py"
    }
    $out = & $Py $Overlay $action 2>&1 | Out-String
    $code = $LASTEXITCODE
    if ($out) {
        Write-Host $out
        try { Add-Content -Path $Log -Value $out -Encoding ascii } catch {}
    }
    if ($null -eq $code) { return 0 }
    return [int]$code
}

if (-not (Test-Path $HermesExe)) {
    Write-Host "venv hermes.exe missing - run Phronesis-Hermes-Venv-Recover.ps1 first" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Overlay)) {
    Write-Host "overlay door missing: $Overlay" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $UpdateDoor)) {
    Write-Host "update door missing: $UpdateDoor" -ForegroundColor Red
    exit 1
}

Write-Host "=== Phronesis Safe Hermes Update ===" -ForegroundColor Cyan
Write-Safe "start export_only=$ExportOnly dry=$DryRun noreapply=$NoReapply resume=$Resume"

if (-not $ExportOnly -and -not $DryRun) {
    Write-Safe "preflight hermes_update_once.py"
    $preOut = & $Py $UpdateDoor preflight 2>&1 | Out-String
    $preRc = $LASTEXITCODE
    if ($preOut) {
        Write-Host $preOut
        try { Add-Content -Path $Log -Value $preOut -Encoding ascii } catch {}
    }
    if ($null -eq $preRc) { $preRc = 1 }
    if ([int]$preRc -ne 0) {
        Write-Host "Preflight refused apply. Measure: python D:\HermesData\scripts\ops\hermes_update_once.py status" -ForegroundColor Red
        Write-Host "Do not use the Desktop Update button. Do not hermes update --force-venv." -ForegroundColor Red
        exit [int]$preRc
    }
}

if ($Resume) {
    Write-Safe "resume: skip export+unload (keep existing overlay)"
    $man = Join-Path $HermesRoot "house-overlays\hermes-agent\latest\MANIFEST.json"
    if (-not (Test-Path $man)) {
        Write-Host "Resume refused: no overlay MANIFEST at house-overlays\hermes-agent\latest" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Safe "overlay export"
    $exportRc = Invoke-Overlay "export"
    if ($exportRc -ne 0) {
        Write-Host "overlay export failed (exit $exportRc). See $Log" -ForegroundColor Red
        exit $exportRc
    }

    if ($ExportOnly -or $DryRun) {
        Write-Safe "stop after export/dry-run"
        Write-Host "House overlay snapshotted at D:\HermesData\house-overlays\hermes-agent\latest" -ForegroundColor Green
        Write-Host "Receipt: D:\HermesData\state\hermes_house_overlay_latest.json"
        exit 0
    }

    Write-Safe "overlay unload (revert hermes-agent house patches)"
    $unloadRc = Invoke-Overlay "unload"
    if ($unloadRc -ne 0) {
        Write-Host "overlay unload failed (exit $unloadRc). Tree may still be dirty." -ForegroundColor Red
        exit $unloadRc
    }
}

$quietFlags = @(
    "hermes_update.IN_PROGRESS",
    "silo_continuous.STOP",
    "silo_autonomous.STOP",
    "popup_emergency.STOP",
    "hermes_ops_quiet.ON"
)
$preexist = @{}
foreach ($f in $quietFlags) {
    $preexist[$f] = Test-Path (Join-Path $State $f)
}

Write-Safe "quiet kitchen"
& powershell -NoProfile -ExecutionPolicy Bypass -File $Quiet
Start-Sleep -Seconds 3

function Get-VenvHolderCount {
    $rows = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and ($_.CommandLine -like "*hermes-agent\venv*")
    })
    return $rows.Count
}

$holders = Get-VenvHolderCount
if ($holders -gt 0) {
    Write-Safe "venv holders remaining=$holders - extra StopAll sweep"
    $stopAll = Join-Path $HermesRoot "scripts\Phronesis-Hermes-StopAll.ps1"
    if (Test-Path $stopAll) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $stopAll -Quiet
        Start-Sleep -Seconds 3
    }
    $holders = Get-VenvHolderCount
}
if ($holders -gt 0) {
    Write-Host "Cannot update: $holders venv process(es) still running. Close Hermes Desktop and retry." -ForegroundColor Red
    if (-not $preexist["hermes_update.IN_PROGRESS"]) {
        Remove-Item (Join-Path $State "hermes_update.IN_PROGRESS") -Force -ErrorAction SilentlyContinue
    }
    if (-not $preexist["hermes_ops_quiet.ON"]) {
        Remove-Item (Join-Path $State "hermes_ops_quiet.ON") -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

Start-Sleep -Seconds 2

$updArgs = @("update", "--yes")
if ($Force) { $updArgs += "--force" }
if ($NoBackup) { $updArgs += "--no-backup" }

Write-Safe "running python -m hermes_cli.main $($updArgs -join ' ') cwd=$Agent"
Write-Host "Running: python -m hermes_cli.main $($updArgs -join ' ') (cwd hermes-agent)"
# cwd MUST be hermes-agent. `uv pip install -e .` from D:\HermesData exits 2.
# Use venv python -m hermes_cli so this PS1 does not lock hermes.exe.
$argLine = ($updArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
$prevLoc = Get-Location
Set-Location $Agent
cmd.exe /c "`"$Py`" -m hermes_cli.main $argLine" 1>> $Log 2>&1
$updRc = $LASTEXITCODE
if ($null -eq $updRc) { $updRc = 0 }
Set-Location $prevLoc
Get-Content -Path $Log -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }

# hermes update may spawn its own gateway. Ensure owns the only tree.
Write-Safe "stop updater-spawned gateway before Ensure"
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "hermes_cli\.main gateway|hermes_gateway_service|hermes_meta_watchdog"
} | ForEach-Object {
    Write-Safe "kill updater child $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

Write-Safe "install messaging extras (discord.py)"
& $Py -m pip install --disable-pip-version-check "discord.py[voice]==2.7.1"
if ($LASTEXITCODE -ne 0) {
    Write-Safe "discord.py install failed rc=$LASTEXITCODE"
}

if ($updRc -ne 0) {
    Write-Host "hermes update failed (exit $updRc). Overlay is at house-overlays\hermes-agent\latest" -ForegroundColor Red
    Write-Safe "update failed rc=$updRc - attempting overlay apply + Ensure anyway"
}

if (-not $NoReapply) {
    Write-Safe "overlay apply"
    $applyRc = Invoke-Overlay "apply"
    if ($applyRc -ne 0) {
        Write-Host "overlay apply had conflicts. House copies are in house-overlays\hermes-agent\latest" -ForegroundColor Yellow
        Write-Safe "apply conflicts rc=$applyRc"
    }
} else {
    Write-Safe "skip reapply (vanilla tree)"
}

# Git/zip update wipes gitignored apps/desktop/release. Rebuild Start Menu exe.
$deskExe = Join-Path $Agent "apps\desktop\release\win-unpacked\Hermes.exe"
if (-not (Test-Path $deskExe)) {
    Write-Safe "desktop win-unpacked missing - hermes desktop --build-only"
    $prevLoc2 = Get-Location
    Set-Location $Agent
    cmd.exe /c "`"$Py`" -m hermes_cli.main desktop --build-only --hermes-root `"$Agent`"" 1>> $Log 2>&1
    $deskRc = $LASTEXITCODE
    Set-Location $prevLoc2
    if ($deskRc -ne 0 -or -not (Test-Path $deskExe)) {
        Write-Safe "desktop rebuild failed rc=$deskRc (Start Menu uses Start-Hermes-Desktop.ps1 fallback)"
    } else {
        Write-Safe "desktop rebuilt $deskExe"
    }
}

Write-Safe "Ensure-HermesStack-Single -AlsoProxy"
& powershell -NoProfile -ExecutionPolicy Bypass -File $Ensure -AlsoProxy

foreach ($f in $quietFlags) {
    if (-not $preexist[$f]) {
        Remove-Item (Join-Path $State $f) -Force -ErrorAction SilentlyContinue
        Write-Safe "cleared $f"
    }
}

Write-Safe "SAT --status-only (no heal)"
& $Py (Join-Path $HermesRoot "scripts\ops\speak_and_trust_once.py") --status-only

if ($updRc -ne 0) {
    Write-Host "=== Safe update FAILED - kitchen restore attempted. Log: $Log ===" -ForegroundColor Red
    exit $updRc
}

Write-Host "=== Safe update complete. Overlay receipt: D:\HermesData\state\hermes_house_overlay_latest.json ===" -ForegroundColor Green
Write-Safe "done"
exit 0
