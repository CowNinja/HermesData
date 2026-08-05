# REDIRECT 2026-08-05 (P4 ensure collapse)
# Gateway start SSOT: hermes_gateway_service via solid_stack / speak-and-trust.
# Archive: scripts/_archive_ensure_collapse_20260805/Start-Hermes-Gateway-Background.ps1
$Hermes = "D:\HermesData"
$py = Join-Path $Hermes "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Write-Host "REDIRECT: Start-Hermes-Gateway-Background -> speak_and_trust (service owns gateway)"
& $py (Join-Path $Hermes "scripts\ops\speak_and_trust_once.py") --heal
exit $LASTEXITCODE
