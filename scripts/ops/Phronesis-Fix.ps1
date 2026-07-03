# Thin wrapper - Phronesis.ps1 recover
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path (Split-Path $PSScriptRoot -Parent) "Phronesis.ps1") recover
exit $LASTEXITCODE