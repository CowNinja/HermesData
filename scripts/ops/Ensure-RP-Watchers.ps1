# Ensure singleton RP delivery daemon + folder watcher for Discord thread.
# Always uses hermes-agent venv; kills any python/pythonw copies of these scripts.
# Stay-up: after launch, verify lock PID is alive + hermes-agent venv; retry once.
param(
    [string]$Channel = "1524821864956956793",
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
$statusPath = Join-Path $root "state\rp-watchers-status.json"
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

function Test-DaemonHealthy {
    if (-not (Test-Path $lock)) { return $false }
    $raw = (Get-Content $lock -Raw -ErrorAction SilentlyContinue).Trim()
    $lockPid = 0
    if (-not [int]::TryParse($raw, [ref]$lockPid)) { return $false }
    if (-not (Test-PidAlive $lockPid)) { return $false }
    $aliveProc = Get-CimInstance Win32_Process -Filter "ProcessId=$lockPid" -ErrorAction SilentlyContinue
    if (-not $aliveProc) { return $false }
    if ($aliveProc.CommandLine -notmatch 'hermes-agent\\venv') { return $false }
    if ($aliveProc.CommandLine -notmatch 'comfy_delivery_daemon\.py') { return $false }
    return $true
}

function Start-DeliveryDaemon {
    param([int]$attempt = 1)
    if (-not ((Test-Path $pyw) -and (Test-Path $daemon))) {
        Log "ERROR missing pyw or daemon script"
        return $false
    }
    [void](Stop-Matching 'comfy_delivery_daemon\.py' 'delivery daemon')
    if (Test-Path $lock) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Log "cleared delivery daemon lock"
    }
    Start-Process -FilePath $pyw -ArgumentList @($daemon, "--daemon", "--channel", $Channel) -WindowStyle Hidden
    Start-Sleep -Seconds 2
    if (Test-DaemonHealthy) {
        $pidNow = (Get-Content $lock -Raw).Trim()
        Log "delivery daemon started channel=$Channel pid=$pidNow attempt=$attempt"
        return $true
    }
    # Retry once after clearing stale lock again
    if ($attempt -lt 2) {
        Log "delivery daemon lock/PID verify failed attempt=$attempt — retry"
        Start-Sleep -Seconds 1
        return (Start-DeliveryDaemon -attempt ($attempt + 1))
    }
    Log "ERROR delivery daemon failed to stay up after $attempt attempts channel=$Channel"
    return $false
}

function Write-Status([hashtable]$fields) {
    try {
        $obj = [ordered]@{
            at = (Get-Date).ToString("s")
            channel = $Channel
            image_pipeline_paused = $imagePaused
        }
        foreach ($k in $fields.Keys) { $obj[$k] = $fields[$k] }
        ($obj | ConvertTo-Json -Depth 4) | Set-Content -Path $statusPath -Encoding UTF8
    } catch {}
}

Clear-StaleLock $renderLock

$daemonOk = $false
$watcherOk = $false
$daemonPidOut = 0
$watcherPidOut = 0

# --- Delivery daemon (singleton; off when image pipeline paused) ---
if ($imagePaused) {
    $stopped = Stop-Matching 'comfy_delivery_daemon\.py' 'delivery daemon (paused)'
    if ($stopped -gt 0) { Log "image pipeline paused - stopped delivery daemon" }
    if (Test-Path $lock) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Log "cleared delivery daemon lock (paused)"
    }
    Log "AMBER: image pipeline paused — delivery stay-up skipped (daemon intentionally down)"
    $daemonOk = $true  # intentional off
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
        if ($aliveProc -and $aliveProc.CommandLine -match 'hermes-agent\\venv' -and $aliveProc.CommandLine -match 'comfy_delivery_daemon\.py') {
            $daemonIsHermes = $true
        }
    }

    if ($ForceRestart -or -not $daemonAlive -or -not $daemonIsHermes) {
        $daemonOk = Start-DeliveryDaemon
    } else {
        Log "delivery daemon alive pid=$daemonPid channel=$Channel"
        $daemonOk = $true
    }
    if (Test-Path $lock) {
        [void][int]::TryParse((Get-Content $lock -Raw).Trim(), [ref]$daemonPidOut)
    }
    # Final health gate
    if (-not (Test-DaemonHealthy)) {
        $daemonOk = $false
        Log "ERROR delivery daemon not healthy after ensure"
    } else {
        $daemonOk = $true
    }
}

# --- Folder watcher (singleton, hermes venv only; off when image pipeline paused) ---
if ($imagePaused) {
    $stoppedWatch = Stop-Matching 'watch_comfy_delivery\.py' 'delivery watcher (paused)'
    if ($stoppedWatch -gt 0) { Log "image pipeline paused - stopped delivery watcher" }
    $watcherOk = $true
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
        $watcherOk = $true
        $watcherPidOut = [int]$goodWatch[0].ProcessId
    } elseif ((Test-Path $py) -and (Test-Path $watcher)) {
        Start-Process -FilePath $py -ArgumentList @($watcher, "--channel", $Channel) -WindowStyle Hidden
        Start-Sleep -Seconds 1
        $verify = @(Get-MatchingProcs 'watch_comfy_delivery\.py' | Where-Object { $_.CommandLine -match 'hermes-agent\\venv' })
        if ($verify.Count -ge 1) {
            Log "delivery watcher started channel=$Channel pid=$($verify[0].ProcessId)"
            $watcherOk = $true
            $watcherPidOut = [int]$verify[0].ProcessId
        } else {
            Log "ERROR delivery watcher failed to stay up channel=$Channel"
            $watcherOk = $false
        }
    } else {
        Log "ERROR missing py or watcher script"
        $watcherOk = $false
    }
}

# Rider disabled: agent gateway + comfy_delivery_daemon are the only posters (no triple delivery).
[void](Stop-Matching 'roleplay-image-rider' 'legacy image rider')

Write-Status @{
    daemon_ok = $daemonOk
    watcher_ok = $watcherOk
    daemon_pid = $daemonPidOut
    watcher_pid = $watcherPidOut
    force_restart = [bool]$ForceRestart
}

if (-not $imagePaused -and (-not $daemonOk -or -not $watcherOk)) {
    exit 1
}
exit 0
