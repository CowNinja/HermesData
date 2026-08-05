# REDIRECT 2026-08-05 (P4 ensure collapse)
# Proxy ensure SSOT: ensure_single_proxy_8091.py (kitchen helper) via solid_stack / speak-and-trust.
# Do NOT Start-ScheduledTask Hermes_Proxy_8091 (parked dual).
# Archive: scripts/_archive_ensure_collapse_20260805/Ensure-Sovereign-Proxy-8091.ps1
$ErrorActionPreference = "Continue"
$Hermes = "D:\HermesData"
$py = Join-Path $Hermes "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Write-Host "REDIRECT: proxy heal via kitchen helper ensure_single_proxy_8091.py (not dual schtask)."
& $py (Join-Path $Hermes "scripts\ensure_single_proxy_8091.py")
exit $LASTEXITCODE
