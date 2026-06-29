# 05-stop-all.ps1 — Kill all managed processes
# Usage:  D:\HermesData\scripts\ops\05-stop-all.ps1

param(
    [switch]$Force = $false
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping all Phoenix Sovereign services..." -ForegroundColor Yellow

$targets = @("llama-server", "python")

foreach ($proc in $targets) {
    $existing = Get-Process -Name $proc -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Killing $proc (PID: $($existing.Id -join ', '))..." -ForegroundColor Cyan
        Stop-Process -Name $proc -Force
    } else {
        Write-Host "  $proc not running." -ForegroundColor DarkGray
    }
}

Start-Sleep -Seconds 3
Write-Host "`nAll services stopped." -ForegroundColor Green
