# Ensure singleton Grok direct Discord bridge (Jeff <-> cloud Grok).
param(
    [switch]$Quiet,
    [switch]$Restart,
    [string]$Model = ""
)

# Focus mode: no work, no child spawn (RDP typing / remote)
if (Test-Path "D:\HermesData\state\silo_continuous.STOP") { exit 0 }
if (Test-Path "D:\HermesData\state\silo_autonomous.STOP") { exit 0 }
if (Test-Path "D:\HermesData\state\focus_mode.STOP") { exit 0 }

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
                exit 0
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
    exit 0
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