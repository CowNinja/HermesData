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
& (Join-Path $PSScriptRoot "Phronesis-Hermes-StopAll.ps1")

# Brief wait for Windows to release .pyd handles
Start-Sleep -Seconds 4

$args = @("update", "--yes")
if ($Force) { $args += "--force" }
if ($NoBackup) { $args += "--no-backup" }

Write-Host "Running: hermes $($args -join ' ')"
& $HermesExe @args 2>&1 | Tee-Object -FilePath "D:\HermesData\logs\safe-update-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Update failed (exit $LASTEXITCODE). Run Phronesis-Hermes-Venv-Recover.ps1" -ForegroundColor Red
    exit $LASTEXITCODE
}

& $HermesExe gateway restart 2>&1 | Out-Null
Write-Host "=== Safe update complete ===" -ForegroundColor Green