# Ensure singleton RP delivery daemon + folder watcher for Discord thread.
# Always uses hermes-agent venv; kills any python/pythonw copies of these scripts.
param(
    [string]$Channel = "1521146755985576116",
    [switch]$Quiet,
    [switch]$ForceRestart
)

$root = "D:\HermesData"
$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"
$pyw = Join-Path $root "hermes-agent\venv\Scripts\pythonw.exe"
$daemon = Join-Path $root "scripts\comfy_delivery_daemon.py"
$watcher = Join-Path $root "scripts\ops\watch_comfy_delivery.py"
$lock = Join-Path $root "state\comfy-delivery-daemon.lock"
$renderLock = Join-Path $root "state\roleplay-render.lock"
$pausePath = Join-Path $root "state\image-pipeline-pause.json"
$imagePaused = $false
if (Test-Path $pausePath) {
    try { $imagePaused = [bool]((Get-Content $pausePath -Raw | ConvertFrom-Json).paused) } catch {}
}

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

function Test-PidAlive([int]$processId) {
    if ($processId -le 0) { return $false }
    return [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
}

function Get-MatchingProcs([string]$pattern) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^(python|pythonw)(\.exe)?$' -and
            $_.CommandLine -and
            ($_.CommandLine -match $pattern)
        }
}

function Stop-Matching([string]$pattern, [string]$label) {
    $procs = @(Get-MatchingProcs $pattern)
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Log "stopped $label pid=$($p.ProcessId)"
    }
    return $procs.Count
}

function Clear-StaleLock([string]$path) {
    if (-not (Test-Path $path)) { return }
    $raw = (Get-Content $path -Raw -ErrorAction SilentlyContinue).Trim()
    $lockPid = 0
    [void][int]::TryParse($raw, [ref]$lockPid)
    if (-not (Test-PidAlive $lockPid)) {
        Remove-Item $path -Force -ErrorAction SilentlyContinue
        Log "cleared stale lock $path (pid=$lockPid)"
    }
}

Clear-StaleLock $renderLock

# --- Delivery daemon (singleton; off when image pipeline paused) ---
if ($imagePaused) {
    $stopped = Stop-Matching 'comfy_delivery_daemon\.py' 'delivery daemon (paused)'
    if ($stopped -gt 0) { Log "image pipeline paused - stopped delivery daemon" }
    if (Test-Path $lock) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Log "cleared delivery daemon lock (paused)"
    }
} else {
$daemonPid = 0
if (Test-Path $lock) {
    $raw = (Get-Content $lock -Raw -ErrorAction SilentlyContinue).Trim()
    [void][int]::TryParse($raw, [ref]$daemonPid)
}

$daemonAlive = Test-PidAlive $daemonPid
$daemonIsHermes = $false
if ($daemonAlive) {
    $aliveProc = Get-CimInstance Win32_Process -Filter "ProcessId=$daemonPid" -ErrorAction SilentlyContinue
    if ($aliveProc -and $aliveProc.CommandLine -match 'hermes-agent\\venv') {
        $daemonIsHermes = $true
    }
}

if ($ForceRestart -or -not $daemonAlive -or -not $daemonIsHermes) {
    [void](Stop-Matching 'comfy_delivery_daemon\.py' 'delivery daemon')
    if (Test-Path $lock) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Log "cleared delivery daemon lock"
    }
    if ((Test-Path $pyw) -and (Test-Path $daemon)) {
        Start-Process -FilePath $pyw -ArgumentList @($daemon, "--daemon", "--channel", $Channel) -WindowStyle Hidden
        Start-Sleep -Seconds 2
        if (Test-Path $lock) {
            Log "delivery daemon started channel=$Channel pid=$((Get-Content $lock -Raw).Trim())"
        } else {
            Log "delivery daemon launch requested (lock pending) channel=$Channel"
        }
    } else {
        Log "ERROR missing pyw or daemon script"
    }
} else {
    Log "delivery daemon alive pid=$daemonPid channel=$Channel"
}
}

# --- Folder watcher (singleton, hermes venv only; off when image pipeline paused) ---
if ($imagePaused) {
    $stoppedWatch = Stop-Matching 'watch_comfy_delivery\.py' 'delivery watcher (paused)'
    if ($stoppedWatch -gt 0) { Log "image pipeline paused - stopped delivery watcher" }
} else {
$watchProcs = @(Get-MatchingProcs 'watch_comfy_delivery\.py')
$goodWatch = @($watchProcs | Where-Object { $_.CommandLine -match 'hermes-agent\\venv' })
$badWatch = @($watchProcs | Where-Object { $_.CommandLine -notmatch 'hermes-agent\\venv' })

foreach ($p in $badWatch) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Log "stopped non-hermes delivery watcher pid=$($p.ProcessId)"
}

if ($ForceRestart) {
    foreach ($p in $goodWatch) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Log "stopped delivery watcher pid=$($p.ProcessId) (force)"
    }
    $goodWatch = @()
}

if ($goodWatch.Count -gt 1) {
    # keep oldest, kill extras
    $keep = $goodWatch | Sort-Object ProcessId | Select-Object -First 1
    foreach ($p in $goodWatch) {
        if ($p.ProcessId -ne $keep.ProcessId) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Log "stopped extra delivery watcher pid=$($p.ProcessId)"
        }
    }
    $goodWatch = @($keep)
}

if ($goodWatch.Count -eq 1) {
    Log "delivery watcher alive pid=$($goodWatch[0].ProcessId)"
} elseif ((Test-Path $py) -and (Test-Path $watcher)) {
    Start-Process -FilePath $py -ArgumentList @($watcher, "--channel", $Channel) -WindowStyle Hidden
    Start-Sleep -Seconds 1
    Log "delivery watcher started channel=$Channel"
} else {
    Log "ERROR missing py or watcher script"
}
}

# Rider disabled: agent gateway + comfy_delivery_daemon are the only posters (no triple delivery).
[void](Stop-Matching 'roleplay-image-rider' 'legacy image rider')
