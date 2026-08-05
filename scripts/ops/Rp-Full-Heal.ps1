# REDIRECT 2026-08-05 (P4 ensure collapse)
# RP full heal freestyle -> speak-and-trust (stack) only; RP content not dual-healed here.
# Archive: scripts/_archive_ensure_collapse_20260805/ops__Rp-Full-Heal.ps1
$Hermes = "D:\HermesData"
$py = Join-Path $Hermes "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Write-Host "REDIRECT: Rp-Full-Heal -> speak_and_trust_once.py (stack SSOT; not RP content rewrite)"
& $py (Join-Path $Hermes "scripts\ops\speak_and_trust_once.py") --heal
exit $LASTEXITCODE
