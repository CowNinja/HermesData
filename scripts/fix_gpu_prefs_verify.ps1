$ErrorActionPreference = "Continue"
$regPath = "HKCU:\Software\Microsoft\DirectX\UserGpuPreferences"
$prefer = "GpuPreference=2;"

# Clean MEmu to pure high-perf
$memu = @(
  "D:\Program Files\Microvirt\MEmu\MEmu.exe",
  "D:\Program Files\Microvirt\MEmu\MEmuConsole.exe",
  "D:\Program Files\Microvirt\MEmuHyperv\MEmuHeadless.exe",
  "D:\Program Files\Microvirt\MEmuHyperv\MEmuHyper.exe",
  "D:\Program Files\Microvirt\MEmuHyperv\MEmuSVC.exe",
  "D:\Program Files\Microvirt\MEmuHyperv\MEmuManage.exe"
)
foreach ($m in $memu) {
  if (Test-Path -LiteralPath $m) {
    New-ItemProperty -Path $regPath -Name $m -Value $prefer -PropertyType String -Force | Out-Null
  }
}

# Clear stuck Sentry locks that can block launches
$removed = New-Object System.Collections.Generic.List[string]
$lockRoots = @(
  "$env:USERPROFILE\AppData\LocalLow\Tomato Cake",
  "$env:USERPROFILE\AppData\LocalLow\Freejam"
)
foreach ($root in $lockRoots) {
  if (-not (Test-Path -LiteralPath $root)) { continue }
  Get-ChildItem -LiteralPath $root -Recurse -Filter "*.lock" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
      $removed.Add($_.FullName)
    } catch {}
  }
}

$props = (Get-ItemProperty $regPath).PSObject.Properties |
  Where-Object { $_.Name -notmatch "^PS" -and $_.Name -ne "GraphicsFeaturesNotificationConfig" }

$gpu2 = @($props | Where-Object { [string]$_.Value -match "GpuPreference=2" })
$gpu1 = @($props | Where-Object {
  ([string]$_.Value -match "GpuPreference=1") -and ([string]$_.Value -notmatch "GpuPreference=2")
})

Write-Output ("HIGH_PERF_PIN_COUNT=" + $gpu2.Count)
Write-Output ("STILL_POWER_SAVE_COUNT=" + $gpu1.Count)
if ($gpu1.Count -gt 0) {
  $gpu1 | ForEach-Object { Write-Output ("POWER_SAVE: " + $_.Name) }
}

Write-Output "MEmu_VERIFY:"
foreach ($m in $memu) {
  $p = Get-ItemProperty -Path $regPath -Name $m -ErrorAction SilentlyContinue
  if ($p) {
    Write-Output ("  OK " + $m + " = " + $p.$m)
  } else {
    Write-Output ("  MISSING " + $m)
  }
}

Write-Output "LOCKS_REMOVED:"
if ($removed.Count -eq 0) {
  Write-Output "  (none)"
} else {
  $removed | ForEach-Object { Write-Output ("  " + $_) }
}

Write-Output "KEY_GAMES:"
$keys = @(
  "*\War Thunder\win64\aces.exe",
  "*\Enshrouded\enshrouded.exe",
  "*\TS4_x64.exe",
  "*\Albion-Online.exe",
  "*\Trailmakers.exe",
  "*\Robocraft 2.exe",
  "*\robocraftclient.exe",
  "*\PaliaClientSteam-Win64-Shipping.exe",
  "*\PaxDeiClient-Win64-Shipping.exe",
  "*\Unturned.exe",
  "*\hoi4.exe",
  "*\Cities.exe",
  "*\portal2.exe",
  "*\SlimeRancher.exe",
  "*\BoplBattle.exe",
  "*\MEmu.exe",
  "*\steam.exe",
  "*\CivilizationVI.exe"
)
foreach ($k in $keys) {
  $hit = $gpu2 | Where-Object { $_.Name -like $k } | Select-Object -First 1
  if ($hit) {
    Write-Output ("  OK " + $hit.Name)
  } else {
    Write-Output ("  MISS pattern " + $k)
  }
}
