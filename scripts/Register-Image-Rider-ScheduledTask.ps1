# Register Windows scheduled task: Phronesis Image Rider @ logon
$ErrorActionPreference = 'Stop'
$taskName = 'Phronesis-Image-Rider'
$startScript = 'D:\PhronesisVault\Roleplay-Sandbox\scripts\Start-Image-Rider.ps1'
if (-not (Test-Path $startScript)) {
    Write-Error "Missing $startScript"
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description 'Discord roleplay image rider - standard Pony 832x1216 sidecar'
Write-Host "Registered scheduled task: $taskName"