# Thin wrapper - Phronesis.ps1 stop
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path (Split-Path $PSScriptRoot -Parent) "Phronesis.ps1") stop
exit $LASTEXITCODE