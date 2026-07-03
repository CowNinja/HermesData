# Phronesis-Recovery.ps1 - Admin recovery after optimizer side-effects
#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

function Write-H { param([string]$M, [string]$C = "Gray")
    Write-Host "$(Get-Date -Format 'HH:mm:ss') | $M" -ForegroundColor $C
}

$root = Split-Path $PSScriptRoot -Parent
Write-H "========== PHRONESIS RECOVERY ==========" -C Magenta

Write-H "[1/4] Re-enabling WiFi (WlanSvc)..." -C Cyan
try {
    Set-Service WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue
    Start-Service WlanSvc -ErrorAction SilentlyContinue
    $s = Get-Service WlanSvc
    Write-H "  WlanSvc: $($s.StartType) / $($s.Status)" -C Green
} catch { Write-H "  WlanSvc: $_" -C Red }

Write-H "[2/4] Boot simplification (2 tasks only)..." -C Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis-Simplify-Boot.ps1")

Write-H "[3/4] Stack restart..." -C Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis-OneButton-Stop.ps1")
Start-Sleep -Seconds 2
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis-OneButton-Start.ps1")

Write-H "[4/4] Health dashboard..." -C Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Phronesis-Dashboard.ps1")

Write-H "========== RECOVERY COMPLETE ==========" -C Magenta