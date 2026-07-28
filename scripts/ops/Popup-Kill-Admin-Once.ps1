# Popup-Kill-Admin-Once.ps1
# Run elevated ONCE to kill remaining focus-steal schtasks (RDP typing).
# Research: Focus-Steal-Prevention-CANONICAL + incident 2026-07-21
# ASCII-only.

$ErrorActionPreference = "Continue"
$pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) {
  $pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
}
$launch = "D:\HermesData\scripts\launch_hidden_ps.py"
$scripts = "D:\HermesData\scripts"

function Set-HiddenPywTask([string]$Name, [string]$Argument, [string]$WorkDir) {
  try {
    $a = New-ScheduledTaskAction -Execute $pyw -Argument $Argument -WorkingDirectory $WorkDir
    Set-ScheduledTask -TaskName $Name -Action $a -ErrorAction Stop | Out-Null
    Write-Host "OK rebind $Name"
  } catch {
    Write-Host "FAIL rebind $Name : $($_.Exception.Message)"
  }
}

function Disable-TaskSafe([string]$Name) {
  try {
    Disable-ScheduledTask -TaskName $Name -ErrorAction Stop | Out-Null
    Write-Host "OK disable $Name"
  } catch {
    Write-Host "FAIL disable $Name : $($_.Exception.Message)"
  }
}

Write-Host "=== Popup kill admin once ==="
Write-Host "pythonw=$pyw"

# Cua computer-use: AgentCursorOverlay steals RDP focus. Disable logon serve.
# Task is Highest-runlevel; only elevated session can Disable/Delete.
try {
  $cua = "C:\Users\CowNi\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe"
  if (Test-Path $cua) {
    & $cua stop 2>$null
    & $cua autostart disable 2>$null
    Write-Host "OK cua-driver stop + autostart disable attempt"
  }
} catch {
  Write-Host "WARN cua-driver CLI: $($_.Exception.Message)"
}
Disable-TaskSafe "cua-driver-serve"
try {
  Unregister-ScheduledTask -TaskName "cua-driver-serve" -Confirm:$false -ErrorAction Stop
  Write-Host "OK unregister cua-driver-serve"
} catch {
  Write-Host "FAIL unregister cua-driver-serve : $($_.Exception.Message)"
}

# Dual PS entry when Hidden twin exists -- disable flashy PS entry
Disable-TaskSafe "Phronesis-Guardian"
Disable-TaskSafe "Phronesis-Grok-Direct-Bridge"
Disable-TaskSafe "Phronesis-Grok-Hermes-Loop"
Disable-TaskSafe "Phronesis-Image-Rider"
Disable-TaskSafe "Phronesis-Start-At-Logon"

# Rebind (even if disabled) so future Enable is safe
Set-HiddenPywTask "Phronesis-Guardian" "`"$launch`" `"$scripts\Phronesis-Guardian-Body.ps1`"" $scripts
Set-HiddenPywTask "Phronesis-Grok-Direct-Bridge" "`"$launch`" `"$scripts\ops\Ensure-Grok-Direct-Bridge.ps1`" -Quiet" $scripts
Set-HiddenPywTask "Phronesis-Grok-Hermes-Loop" "`"D:\HermesData\temp\grok_hermes_loop.py`" --once" "D:\HermesData"
Set-HiddenPywTask "Phronesis-Image-Rider" "`"$launch`" `"D:\PhronesisVault\Roleplay-Sandbox\scripts\Start-Image-Rider.ps1`"" "D:\PhronesisVault\Roleplay-Sandbox\scripts"
Set-HiddenPywTask "Phronesis-Start-At-Logon" "`"$launch`" `"$scripts\Phronesis-OneButton-Start.ps1`"" $scripts
Set-HiddenPywTask "Hermes_Gateway_Watchdog" "`"$launch`" `"$scripts\ops\hermes_gateway_watchdog.ps1`"" $scripts
Set-HiddenPywTask "Sovereign-Proxy-Watchdog" "`"$launch`" `"$scripts\ops\sovereign-proxy-watchdog.ps1`"" $scripts
Set-HiddenPywTask "Hermes_Gateway_ForceReload_Once" "`"$scripts\ops\gateway_force_reload_once.py`"" "$scripts\ops"

# Keep Hidden twins enabled
try { Enable-ScheduledTask -TaskName "Phronesis-Guardian-Hidden" -ErrorAction SilentlyContinue | Out-Null } catch {}
try { Enable-ScheduledTask -TaskName "Phronesis-Grok-Direct-Bridge-Hidden" -ErrorAction SilentlyContinue | Out-Null } catch {}

# GPU Tweak III / Monitor.exe - SOUI_DUMMY_WND focus steal under RDP
# Disable/delete logon task (Highest often; try anyway when elevated)
Disable-TaskSafe "GPU Tweak III"
try {
  Unregister-ScheduledTask -TaskName "GPU Tweak III" -Confirm:$false -ErrorAction Stop
  Write-Host "OK unregister GPU Tweak III"
} catch {
  Write-Host "FAIL unregister GPU Tweak III : $($_.Exception.Message)"
}
$gpuDir = "C:\Program Files (x86)\ASUS\GPUTweakIII"
foreach ($img in @("GPU Tweak III.exe", "Monitor.exe", "GT3 mobile service.exe", "ASUSGPUFanService.exe", "ASUSGPUFanServiceEx.exe", "ASGT.exe")) {
  try {
    & taskkill /IM $img /F 2>$null | Out-Null
    # WMIC terminate works when taskkill Access-denied
    & wmic process where "name='$img'" call terminate 2>$null | Out-Null
    Write-Host "OK terminate $img"
  } catch {
    Write-Host "WARN terminate $img : $($_.Exception.Message)"
  }
}
# Stop ASUS GPU fan service if present (elevated)
foreach ($svc in @("ASUSGPUFanService", "ASUS GPU Fan Service")) {
  try {
    Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
    Set-Service -Name $svc -StartupType Disabled -ErrorAction SilentlyContinue
    Write-Host "OK service disable attempt $svc"
  } catch {}
}
try {
  $marker = Join-Path $gpuDir "PHRONESIS_DISABLED_AUTOSTART.txt"
  if (Test-Path $gpuDir) {
    "disabled by Popup-Kill-Admin-Once $(Get-Date -Format o)" | Set-Content -Path $marker -Encoding ASCII
    Write-Host "OK wrote $marker"
  }
} catch {}

# Focus mode on + start lightweight storm daemon
& $pyw "D:\HermesData\scripts\focus_mode.py" on --reason "admin_popup_kill"
try {
  $stopD = "D:\HermesData\state\popup_storm_daemon.STOP"
  if (Test-Path $stopD) { Remove-Item $stopD -Force -ErrorAction SilentlyContinue }
  Start-Process -FilePath $pyw -ArgumentList "`"D:\HermesData\scripts\popup_storm_daemon.py`"" -WindowStyle Hidden
  Write-Host "OK popup_storm_daemon start"
} catch {
  Write-Host "WARN daemon: $($_.Exception.Message)"
}

Write-Host "=== Done. Keep Guardian-Hidden + Grok-Direct-Bridge-Hidden. Typing: focus_mode ON. ==="
Write-Host "When kitchen wanted: pythonw D:\HermesData\scripts\focus_mode.py off --resume-hidden"
Write-Host "GPU Tweak: if still running after reboot, uninstall or disable in Task Manager > Startup"
