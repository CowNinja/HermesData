# Phronesis-Guardian.ps1 - schtask entry (often bare powershell.exe; cannot rebind without Admin).
# 2026-07-26: Always FreeConsole + exit under lockdown/STOP so Task Scheduler shows SUCCESS (0)
# instead of 267014 TERMINATED (looks like "error" when suppress force-ends the task).
$ErrorActionPreference = "SilentlyContinue"
try {
  Add-Type -Name K -Namespace W -MemberDefinition '[DllImport("kernel32.dll")] public static extern bool FreeConsole();' -ErrorAction SilentlyContinue
  [W.K]::FreeConsole() | Out-Null
} catch {}
# Permanent travel lockdown + focus STOP - no body, no elevate, no Write-Host.
# Use Environment.Exit so schtasks Last Result is truly 0 (PS `exit 0` can
# still report 1 when non-terminating errors sit in $Error).
function Exit-Ok([string]$reason) {
  try {
    $stamp = "D:\HermesData\state\phronesis_guardian_last_exit.txt"
    Set-Content -Path $stamp -Value ("ok " + $reason + " " + [DateTimeOffset]::UtcNow.ToString("o")) -Encoding ascii -ErrorAction SilentlyContinue
  } catch {}
  [System.Environment]::Exit(0)
}
if (Test-Path "D:\HermesData\state\popup_lockdown.ON") { Exit-Ok "lockdown" }
if (Test-Path "D:\HermesData\state\popup_emergency.STOP") { Exit-Ok "emergency" }
if (Test-Path "D:\HermesData\state\silo_continuous.STOP") { Exit-Ok "silo_continuous_stop" }
if (Test-Path "D:\HermesData\state\silo_autonomous.STOP") { Exit-Ok "silo_autonomous_stop" }
if (Test-Path "D:\HermesData\state\focus_mode.STOP") { Exit-Ok "focus_stop" }
# 30m cadence floor
try {
  $cadenceStamp = "D:\HermesData\state\phronesis_guardian_last_fire.txt"
  $minIntervalSec = 1800
  if (Test-Path $cadenceStamp) {
    $raw = (Get-Content $cadenceStamp -Raw -ErrorAction SilentlyContinue).Trim()
    $lastUnix = 0L
    if ([int64]::TryParse($raw, [ref]$lastUnix)) {
      $nowUnix = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
      if (($nowUnix - $lastUnix) -lt $minIntervalSec) { Exit-Ok "cadence" }
    }
  }
  $nowWrite = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
  Set-Content -Path $cadenceStamp -Value "$nowWrite" -Encoding ascii -NoNewline -ErrorAction SilentlyContinue
} catch {}
if ($env:HERMES_HIDDEN_CHILD -eq "1") {
    & (Join-Path $PSScriptRoot "Phronesis-Guardian-Body.ps1")
    $code = 0
    if ($null -ne $LASTEXITCODE) { $code = [int]$LASTEXITCODE }
    [System.Environment]::Exit($code)
}
$pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$launcher = "D:\HermesData\scripts\launch_hidden_ps.py"
$body = "D:\HermesData\scripts\Phronesis-Guardian-Body.ps1"
if (-not (Test-Path $pyw)) {
    $pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
}
$cmd = '"' + $pyw + '" "' + $launcher + '" "' + $body + '"'
try {
    $w = New-Object -ComObject WScript.Shell
    $null = $w.Run($cmd, 0, $false)
} catch {
    # No Start-Process fallback that can flash - silent fail
}
Exit-Ok "trampoline"
