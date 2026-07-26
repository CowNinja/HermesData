# Ensure singleton Grok direct Discord bridge (Jeff <-> cloud Grok).
param(
    [switch]$Quiet,
    [switch]$Restart,
    [string]$Model = ""
)

$ErrorActionPreference = "SilentlyContinue"
# Detach console ASAP so RDP does not flash even for STOP exit path
try {
  Add-Type -Name K -Namespace W -MemberDefinition '[DllImport("kernel32.dll")] public static extern bool FreeConsole();' -ErrorAction SilentlyContinue
  [W.K]::FreeConsole() | Out-Null
} catch {}

# Lockdown / focus: no work, no child spawn (RDP typing / remote).
# Environment.Exit(0) so schtasks Last Result is truly SUCCESS (PS `exit 0`
# can still report 1 when $Error is non-empty; force-End was 267014).
function Exit-Ok([string]$reason) {
  try {
    $stamp = "D:\HermesData\state\grok_direct_bridge_last_exit.txt"
    Set-Content -Path $stamp -Value ("ok " + $reason + " " + [DateTimeOffset]::UtcNow.ToString("o")) -Encoding ascii -ErrorAction SilentlyContinue
  } catch {}
  [System.Environment]::Exit(0)
}
if (Test-Path "D:\HermesData\state\popup_lockdown.ON") { Exit-Ok "lockdown" }
if (Test-Path "D:\HermesData\state\popup_emergency.STOP") { Exit-Ok "emergency" }
if (Test-Path "D:\HermesData\state\silo_continuous.STOP") { Exit-Ok "silo_continuous_stop" }
if (Test-Path "D:\HermesData\state\silo_autonomous.STOP") { Exit-Ok "silo_autonomous_stop" }
if (Test-Path "D:\HermesData\state\focus_mode.STOP") { Exit-Ok "focus_stop" }

# Cadence floor 2026-07-26: schtask may still be 5m (Admin needed to rebind RI).
# Self-throttle to 30m unless -Restart. Prevents RDP trampoline flash every 5m.
if (-not $Restart) {
  try {
    $cadenceStamp = "D:\HermesData\state\grok_direct_bridge_last_fire.txt"
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
}

# If Task Scheduler started bare powershell (focus steal), bounce into pythonw CREATE_NO_WINDOW.
if ($env:HERMES_HIDDEN_CHILD -ne "1" -and $MyInvocation.InvocationName -ne '.' -and $MyInvocation.Line -notmatch '^\s*\.') {
    # Only trampoline when this file is the entry script, not when dot-sourced from Guardian-Body
    $entry = $MyInvocation.MyCommand.Path
    if ($entry -and (Test-Path $entry)) {
        $pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
        $launcher = "D:\HermesData\scripts\launch_hidden_ps.py"
        if (Test-Path $pyw) {
            $extra = @()
            if ($Quiet) { $extra += "-Quiet" }
            if ($Restart) { $extra += "-Restart" }
            if ($Model) { $extra += @("-Model", $Model) }
            try {
                $w = New-Object -ComObject WScript.Shell
                $arg = "`"$pyw`" `"$launcher`" `"$entry`" " + ($extra -join " ")
                $null = $w.Run($arg, 0, $false)
                Exit-Ok "trampoline"
            } catch {}
        }
    }
}

$root = "D:\HermesData"
$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"
$pyw = Join-Path $root "hermes-agent\venv\Scripts\pythonw.exe"
$bridge = Join-Path $root "scripts\discord_grok_bridge.py"
$setup = Join-Path $root "temp\setup_grok_direct_discord.py"
$config = Join-Path $root "state\grok-direct-discord.json"
$lock = Join-Path $root "state\grok-direct-bridge.lock"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

function Test-PidAlive([int]$processId) {
    if ($processId -le 0) { return $false }
    return [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
}

if (-not (Test-Path $config)) {
    Log "grok-direct config missing - running setup..."
    if (Test-Path $setup) {
        & $py $setup
    } else {
        Write-Host "FATAL: setup script missing at $setup" -ForegroundColor Red
        exit 1
    }
}

$cfg = Get-Content $config -Raw | ConvertFrom-Json
$threadId = [string]$cfg.thread_id
if (-not $threadId) {
    Write-Host "FATAL: thread_id missing in $config" -ForegroundColor Red
    exit 1
}

$yaml = Join-Path $root "config.yaml"
if (Test-Path $yaml) {
    $raw = Get-Content $yaml -Raw
    if ($raw -match [regex]::Escape($threadId)) {
        Log "config.yaml already ignores thread $threadId"
    } else {
        Log "WARN: add discord.ignored_channels: $threadId to config.yaml and restart gateway"
    }
}

$bridgePid = 0
if (Test-Path $lock) {
    $rawLock = (Get-Content $lock -Raw -ErrorAction SilentlyContinue).Trim()
    [void][int]::TryParse($rawLock, [ref]$bridgePid)
}

if ($Restart) {
    if (Test-PidAlive $bridgePid) {
        Stop-Process -Id $bridgePid -Force -ErrorAction SilentlyContinue
        Log "stopped bridge pid=$bridgePid"
    }
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'discord_grok_bridge\.py' } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Log "stopped extra bridge pid=$($_.ProcessId)"
        }
    if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }
    $bridgePid = 0
}

if (Test-PidAlive $bridgePid) {
    Log "grok-direct bridge alive pid=$bridgePid thread=$threadId"
    Exit-Ok "alive"
}
if ((Test-Path $lock) -and -not (Test-PidAlive $bridgePid)) {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    Log "cleared stale grok-direct bridge lock (pid=$bridgePid)"
}

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'discord_grok_bridge\.py' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Log "stopped stale bridge pid=$($_.ProcessId)"
    }
if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }

$bridgeArgs = @($bridge, "--daemon")
if ($Model) { $bridgeArgs += @("--model", $Model) }

if ((Test-Path $pyw) -and (Test-Path $bridge)) {
    Start-Process -FilePath $pyw -ArgumentList $bridgeArgs -WindowStyle Hidden
    Start-Sleep -Seconds 3
    if (Test-Path $lock) {
        Log "grok-direct bridge started thread=$threadId pid=$((Get-Content $lock -Raw).Trim())"
    } else {
        Log "grok-direct bridge launch requested (lock pending) thread=$threadId"
    }
} else {
    Write-Host "FATAL: pythonw or bridge script missing" -ForegroundColor Red
    exit 1
}

if (Test-Path $py) {
    try {
        $smoke = & $py $bridge --test-xai 2>&1 | Out-String
        if ($smoke -match "GROK_DIRECT_OK") { Log "xAI smoke: OK" } else { Log "xAI smoke: $smoke" }
    } catch {
        Log "xAI smoke skipped: $_"
    }
}

$threadName = (Get-Content $config | ConvertFrom-Json).thread_name
Log "thread=$threadId - post from phone in #multi-agent-router -> $threadName"