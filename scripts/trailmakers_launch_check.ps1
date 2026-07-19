$ErrorActionPreference = "Continue"

# Launch via Steam protocol if not running
$tm = Get-Process -Name "Trailmakers" -ErrorAction SilentlyContinue
if (-not $tm) {
  Write-Output "LAUNCHING..."
  Start-Process -FilePath "D:\Program Files (x86)\Steam\steam.exe" -ArgumentList "steam://rungameid/585420"
  Start-Sleep -Seconds 20
} else {
  Write-Output "ALREADY_RUNNING"
}

$tm = Get-Process -Name "Trailmakers" -ErrorAction SilentlyContinue
if ($tm) {
  $tm | Select-Object Name, Id, MainWindowTitle, Responding | Format-List
} else {
  Write-Output "Trailmakers still not running after wait"
}

Write-Output "--- windows ---"
Get-Process | Where-Object { $_.MainWindowTitle -ne "" } |
  Select-Object Name, Id, MainWindowTitle |
  Sort-Object Name |
  Format-Table -AutoSize
