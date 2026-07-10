# watch-workspace.ps1 -- one-shot :3001 liveness check + silent restart if down
# Schedule via Task Scheduler every 5 min, or run from Guardian.
param(
    [switch]$Quiet
)

$wsPort = 3001
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$restart = Join-Path $scriptRoot "restart-workspace.ps1"

function Write-Step([string]$msg) {
    if (-not $Quiet) { Write-Host $msg -ForegroundColor Cyan }
}

$healthy = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$wsPort/api/auth-check" -UseBasicParsing -TimeoutSec 8
    if ($r.StatusCode -eq 200) { $healthy = $true }
}
catch {
    if (-not $Quiet) { Write-Step ("auth-check failed: " + $_.Exception.Message) }
}

if ($healthy) {
    if (-not $Quiet) { Write-Host "Workspace :$wsPort healthy" -ForegroundColor Green }
    exit 0
}

Write-Step "Workspace :$wsPort down -- restarting..."
& powershell -NoProfile -WindowStyle Hidden -File $restart -Quiet
if ($LASTEXITCODE -eq 0) {
    if (-not $Quiet) { Write-Host "Workspace :$wsPort restarted" -ForegroundColor Green }
    exit 0
}
Write-Host "Workspace restart failed (exit $LASTEXITCODE)" -ForegroundColor Red
exit 1