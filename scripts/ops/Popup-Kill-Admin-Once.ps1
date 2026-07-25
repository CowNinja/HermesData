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

# Focus mode on
& $pyw "D:\HermesData\scripts\focus_mode.py" on --reason "admin_popup_kill"

Write-Host "=== Done. Keep Guardian-Hidden + Grok-Direct-Bridge-Hidden. Typing: focus_mode ON. ==="
Write-Host "When kitchen wanted: pythonw D:\HermesData\scripts\focus_mode.py off --resume-hidden"
