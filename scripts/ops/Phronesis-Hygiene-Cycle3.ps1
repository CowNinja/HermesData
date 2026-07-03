# RETIRED stub - Phronesis.ps1 heal + dashboard
Write-Warning "Phronesis-Hygiene-Cycle3.ps1 retired. Running: Phronesis.ps1 heal + dashboard"
$root = Split-Path $PSScriptRoot -Parent
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis.ps1") heal -ForceGateway
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis.ps1") dashboard