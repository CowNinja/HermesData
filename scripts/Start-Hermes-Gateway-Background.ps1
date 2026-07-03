# Thin wrapper - use: Phronesis.ps1 gateway start
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Phronesis.ps1") gateway start
exit $LASTEXITCODE