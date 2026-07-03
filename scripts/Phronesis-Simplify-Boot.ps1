# Phronesis-Simplify-Boot.ps1 - Run ONCE (elevated) to disable chaos, enable 2 tasks only.
# Usage:  powershell -ExecutionPolicy Bypass -File D:\HermesData\scripts\Phronesis-Simplify-Boot.ps1

$ErrorActionPreference = "Continue"
$oneButton = "D:\HermesData\scripts\Phronesis-OneButton-Start.ps1"
$guardian  = "D:\HermesData\scripts\Phronesis-Guardian.ps1"

Write-Host "=== Phronesis Boot Simplification ===" -ForegroundColor Cyan

# DISABLE redundant scheduled tasks
$disable = @(
    "HermesStackBoot",
    "HermesStackWatchdog",
    "Hermes_Gateway",
    "Hermes_Gateway_Watchdog",
    "Hermes_Workspace",
    "Hermes_Workspace_Repair",
    "Sovereign-Proxy-Watchdog",
    "Phronesis-LogIntelligence-Cron"
)
foreach ($t in $disable) {
    schtasks /Change /TN "\$t" /DISABLE 2>$null | Out-Null
    Disable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null
    Write-Host "  Disabled: $t" -ForegroundColor DarkYellow
}

# REGISTER exactly 2 tasks
schtasks /Delete /TN "\Phronesis-Start-At-Logon" /F 2>$null | Out-Null
schtasks /Delete /TN "\Phronesis-Guardian" /F 2>$null | Out-Null

$startAction = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$oneButton`""
schtasks /Create /TN "\Phronesis-Start-At-Logon" /TR $startAction /SC ONLOGON /RL LIMITED /F | Out-Null
Write-Host "  Created: Phronesis-Start-At-Logon (at logon)" -ForegroundColor Green

$guardAction = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$guardian`""
schtasks /Create /TN "\Phronesis-Guardian" /TR $guardAction /SC MINUTE /MO 5 /RL LIMITED /F | Out-Null
Write-Host "  Created: Phronesis-Guardian (every 5 min, single pass)" -ForegroundColor Green

Write-Host "`nBoot reduced to 2 tasks. Old watchdogs disabled." -ForegroundColor Green
Write-Host "Manual start anytime: powershell -File $oneButton" -ForegroundColor Cyan