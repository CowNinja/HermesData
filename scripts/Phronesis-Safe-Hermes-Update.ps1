# Safe Hermes update - stops all venv lock-holders BEFORE update/installer runs.
# Use this instead of clicking Update in Desktop while gateway/rider/proxy are live.
param(
    [switch]$Force,
    [switch]$NoBackup
)

$ErrorActionPreference = "Stop"
$HermesExe = "D:\HermesData\hermes-agent\venv\Scripts\hermes.exe"

if (-not (Test-Path $HermesExe)) {
    Write-Host "venv hermes.exe missing - run Phronesis-Hermes-Venv-Recover.ps1 first" -ForegroundColor Red
    exit 1
}

Write-Host "=== Phronesis Safe Hermes Update ===" -ForegroundColor Cyan

# Guardian (5m heal) and ForkGuard respawn proxy/gateway and block venv updates.
$guardianWasRunning = $false
try {
    $gt = Get-ScheduledTask -TaskName "Phronesis-Guardian" -ErrorAction SilentlyContinue
    if ($gt -and $gt.State -eq "Running") {
        $guardianWasRunning = $true
        Stop-ScheduledTask -TaskName "Phronesis-Guardian" -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName "Phronesis-Guardian" -ErrorAction SilentlyContinue | Out-Null
        Write-Host "Paused Phronesis-Guardian for update window" -ForegroundColor Yellow
    }
} catch {}

$lockPath = "D:\HermesData\state\maintenance-lock.json"
$lockUntil = (Get-Date).AddMinutes(45).ToString("o")
@{
    reason           = "hermes_update"
    until            = $lockUntil
    protect_vram     = $false
    block_stack_heal = $true
    set_at           = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -Path $lockPath -Encoding UTF8

function Get-VenvLockHolderCount {
    $n = 0
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return }
        if ($cmd -like "*hermes-agent\venv*") { $script:n++ }
    }
    return $n
}

$stopAll = Join-Path $PSScriptRoot "Phronesis-Hermes-StopAll.ps1"
for ($attempt = 1; $attempt -le 5; $attempt++) {
    & $stopAll -Quiet
    Start-Sleep -Seconds 3
    $holders = Get-VenvLockHolderCount
    if ($holders -eq 0) { break }
    Write-Host "  venv lock-holders remaining: $holders (attempt $attempt/5)" -ForegroundColor Yellow
}
if ((Get-VenvLockHolderCount) -gt 0) {
    Write-Host "Cannot update: venv processes still running. Close Hermes Desktop and retry." -ForegroundColor Red
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
    if ($guardianWasRunning) { Enable-ScheduledTask -TaskName "Phronesis-Guardian" -ErrorAction SilentlyContinue | Out-Null }
    exit 1
}

# Brief wait for Windows to release .pyd handles
Start-Sleep -Seconds 4

$args = @("update", "--yes")
if ($Force) { $args += "--force" }
if ($NoBackup) { $args += "--no-backup" }

Write-Host "Running: hermes $($args -join ' ')"
& $HermesExe @args 2>&1 | Tee-Object -FilePath "D:\HermesData\logs\safe-update-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Update failed (exit $LASTEXITCODE). Run Phronesis-Hermes-Venv-Recover.ps1" -ForegroundColor Red
    if (Test-Path $lockPath) { Remove-Item $lockPath -Force -ErrorAction SilentlyContinue }
    if ($guardianWasRunning) {
        Enable-ScheduledTask -TaskName "Phronesis-Guardian" -ErrorAction SilentlyContinue | Out-Null
    }
    exit $LASTEXITCODE
}

Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
if ($guardianWasRunning) {
    Enable-ScheduledTask -TaskName "Phronesis-Guardian" -ErrorAction SilentlyContinue | Out-Null
}

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Phronesis-Heal.ps1") -Quiet | Out-Null
Write-Host "=== Safe update complete - stack healed ===" -ForegroundColor Green