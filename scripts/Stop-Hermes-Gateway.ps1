# Thin wrapper - use: Phronesis.ps1 gateway stop
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Phronesis.ps1") gateway stop
exit $LASTEXITCODE