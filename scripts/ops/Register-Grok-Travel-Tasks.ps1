# Register travel-mode scheduled tasks: bridge watchdog (5m) + Hermes collab loop (6h).
# Run once (elevated if schtasks requires): powershell -File D:\HermesData\scripts\ops\Register-Grok-Travel-Tasks.ps1

$ErrorActionPreference = "Continue"
$root = "D:\HermesData"
$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"
$ensureBridge = Join-Path $root "scripts\ops\Ensure-Grok-Direct-Bridge.ps1"
$guardian = Join-Path $root "scripts\Phronesis-Guardian.ps1"
$hermesLoop = Join-Path $root "temp\grok_hermes_loop.py"

if (-not (Test-Path $ensureBridge)) {
    Write-Error "Missing $ensureBridge"
}

# Dedicated bridge watchdog every 5 minutes (belt)
$bridgeTask = "Phronesis-Grok-Direct-Bridge"
schtasks /Delete /TN "\$bridgeTask" /F 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { $LASTEXITCODE = 0 }
$bridgeAction = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ensureBridge`" -Quiet"
schtasks /Create /TN "\$bridgeTask" /TR $bridgeAction /SC MINUTE /MO 5 /RL LIMITED /F | Out-Null
Write-Host "Registered: $bridgeTask (every 5 min)" -ForegroundColor Green

# Guardian already runs every 5 min — ensure it includes travel stack hooks
if (Test-Path $guardian) {
    Write-Host "Guardian travel hooks: Ensure-Grok-Direct-Bridge + inbox + heartbeat + fullstack health" -ForegroundColor Cyan
} else {
    Write-Host "WARN: Phronesis-Guardian.ps1 not found" -ForegroundColor Yellow
}

# Unattended Grok↔Hermes collab (no Cursor/PowerShell required) — every 6h
$loopTask = "Phronesis-Grok-Hermes-Loop"
if ((Test-Path $py) -and (Test-Path $hermesLoop)) {
    schtasks /Delete /TN "\$loopTask" /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $LASTEXITCODE = 0 }
    $loopAction = "`"$py`" `"$hermesLoop`" --once"
    schtasks /Create /TN "\$loopTask" /TR $loopAction /SC HOURLY /MO 6 /RL LIMITED /F | Out-Null
    Write-Host "Registered: $loopTask (every 6 hours, --once)" -ForegroundColor Green
} else {
    Write-Host "WARN: skip $loopTask - python or grok_hermes_loop.py missing" -ForegroundColor Yellow
}

Write-Host 'Done. Verify: schtasks /Query /TN \Phronesis-Grok-Direct-Bridge /V /FO LIST' -ForegroundColor Cyan