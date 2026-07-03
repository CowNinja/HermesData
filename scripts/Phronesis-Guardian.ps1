# Phronesis-Guardian.ps1 - Scheduled health pass (every 5 min). Thin wrapper over Phronesis-Heal.ps1
$ErrorActionPreference = "SilentlyContinue"
$result = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Phronesis-Heal.ps1") -Quiet
exit $(if ($result -and $result.ExitCode -ne $null) { $result.ExitCode } else { 0 })