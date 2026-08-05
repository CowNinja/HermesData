# REDIRECT 2026-08-05 (P4 ensure collapse)
# Full freestyle heal collapsed to Speak-and-Trust / solid_stack_law.
# Archive: scripts/_archive_ensure_collapse_20260805/ops__Magic-Heal.ps1
param([switch]$Quiet)
$Hermes = "D:\HermesData"
$py = Join-Path $Hermes "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
if (-not $Quiet) {
    Write-Host "REDIRECT: Magic-Heal -> speak_and_trust_once.py (single recovery door)"
}
& $py (Join-Path $Hermes "scripts\ops\speak_and_trust_once.py") --heal
exit $LASTEXITCODE
