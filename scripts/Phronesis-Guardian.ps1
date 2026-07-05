# Phronesis-Guardian.ps1 - Scheduled health pass (every 5 min). Thin wrapper over Phronesis-Heal.ps1
$ErrorActionPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "Phronesis-Maintenance-Lock.ps1")
$block = Test-PhronesisMaintenanceBlocked -Action stack_heal
if ($block.blocked) { exit 0 }
$result = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Phronesis-Heal.ps1") -Quiet
exit $(if ($result -and $result.ExitCode -ne $null) { $result.ExitCode } else { 0 })