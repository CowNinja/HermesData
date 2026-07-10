# heal-all-dashboards.ps1 -- restore :9119 CLI + :3001 workspace
param(
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$heal9119 = Join-Path $scriptRoot "05-heal-dashboard.ps1"
$heal3001 = Join-Path $scriptRoot "restart-workspace.ps1"

function Write-Step([string]$msg) {
    if (-not $Quiet) { Write-Host $msg -ForegroundColor Cyan }
}

Write-Step "Healing workspace :3001..."
$wsArgs = @("-NoProfile", "-File", $heal3001)
if ($Quiet) { $wsArgs += "-Quiet" }
& powershell @wsArgs
$wsOk = ($LASTEXITCODE -eq 0)

Write-Step "Healing CLI dashboard :9119..."
& powershell -NoProfile -File $heal9119 -Force
$dashOk = ($LASTEXITCODE -eq 0)

if ($wsOk -and $dashOk) {
    if (-not $Quiet) {
        Write-Host "Both dashboards UP (:9119 + :3001)" -ForegroundColor Green
    }
    exit 0
}

if (-not $Quiet) {
    Write-Host "Partial heal: workspace=$wsOk dashboard=$dashOk" -ForegroundColor Yellow
}
if (-not $wsOk) { exit 2 }
exit 1