# Thin wrapper - Phronesis.ps1 restart
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path (Split-Path $PSScriptRoot -Parent) "Phronesis.ps1") restart
exit $LASTEXITCODE