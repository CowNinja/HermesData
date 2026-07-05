# restart-workspace.ps1 -- reliable :3001 Hermes Workspace restart after Vite rebuild or crash
# Usage:
#   powershell -File D:\HermesData\scripts\ops\restart-workspace.ps1
#   powershell -File D:\HermesData\scripts\ops\restart-workspace.ps1 -Build
param(
    [switch]$Build,
    [switch]$Quiet
)

$ErrorActionPreference = "SilentlyContinue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "..\Phronesis-ForkGuard.ps1")

$wsPort = 3001
$wsDir = "D:\HermesData\hermes-workspace"
if ($Core) {
    if ($Core.ports.workspace) { $wsPort = [int]$Core.ports.workspace }
    if ($Core.workspace_dir) { $wsDir = [string]$Core.workspace_dir }
}

function Write-Step([string]$msg) {
    if (-not $Quiet) { Write-Host $msg -ForegroundColor Cyan }
}

Write-Step "Stopping stale workspace listeners on :$wsPort..."
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'server-entry\.js' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-NetTCPConnection -LocalPort $wsPort -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

if ($Build) {
    Write-Step "Building hermes-workspace (vite)..."
    Push-Location $wsDir
    & npx vite build 2>&1 | Out-Null
    $buildOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $buildOk) {
        Write-Host "vite build FAILED" -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path (Join-Path $wsDir "server-entry.js"))) {
    Write-Host "server-entry.js missing in $wsDir" -ForegroundColor Red
    exit 1
}

Write-Step "Starting workspace server-entry.js..."
if (-not (Start-WorkspaceServer)) {
    Write-Host "Start-WorkspaceServer failed" -ForegroundColor Red
    exit 1
}

if (-not (Wait-PortUp -Port $wsPort -MaxSeconds 40)) {
    Write-Host "Workspace :$wsPort did not bind" -ForegroundColor Red
    exit 1
}

# auth-check is the reliable liveness probe (SSR root may 500 during cold start)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$wsPort/api/auth-check" -UseBasicParsing -TimeoutSec 15
    if ($r.StatusCode -ne 200) {
        Write-Host "auth-check probe failed status $($r.StatusCode)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "auth-check probe failed: $_" -ForegroundColor Red
    exit 1
}

if (-not $Quiet) {
    Write-Host "Workspace :$wsPort UP (auth-check OK). Hard refresh Ctrl+Shift+R on /dashboard" -ForegroundColor Green
}
exit 0