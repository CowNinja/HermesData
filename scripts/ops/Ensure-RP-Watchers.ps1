# Ensure singleton RP delivery daemon + folder watcher for Discord thread.
param(
    [string]$Channel = "1521146755985576116",
    [switch]$Quiet
)

$root = "D:\HermesData"
$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"
$pyw = Join-Path $root "hermes-agent\venv\Scripts\pythonw.exe"
$daemon = Join-Path $root "scripts\comfy_delivery_daemon.py"
$watcher = Join-Path $root "scripts\ops\watch_comfy_delivery.py"
$lock = Join-Path $root "state\comfy-delivery-daemon.lock"
$renderLock = Join-Path $root "state\roleplay-render.lock"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

function Test-PidAlive([int]$processId) {
    if ($processId -le 0) { return $false }
    return [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
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

$daemonPid = 0
if (Test-Path $lock) {
    $raw = (Get-Content $lock -Raw -ErrorAction SilentlyContinue).Trim()
    [void][int]::TryParse($raw, [ref]$daemonPid)
}

if (Test-PidAlive $daemonPid) {
    Log "delivery daemon alive pid=$daemonPid channel=$Channel"
} else {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'comfy_delivery_daemon\.py' } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Log "stopped extra delivery daemon pid=$($_.ProcessId)"
        }
    if (Test-Path $lock) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Log "cleared delivery daemon lock"
    }
    if ((Test-Path $pyw) -and (Test-Path $daemon)) {
        Start-Process -FilePath $pyw -ArgumentList $daemon, "--daemon", "--channel", $Channel -WindowStyle Hidden
        Start-Sleep -Seconds 2
        if (Test-Path $lock) {
            Log "delivery daemon started channel=$Channel pid=$((Get-Content $lock -Raw).Trim())"
        } else {
            Log "delivery daemon launch requested (lock pending) channel=$Channel"
        }
    }
}

$watchRunning = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'watch_comfy_delivery\.py' } |
    Select-Object -First 1

if ($watchRunning) {
    Log "delivery watcher alive pid=$($watchRunning.ProcessId)"
} elseif ((Test-Path $py) -and (Test-Path $watcher)) {
    Start-Process -FilePath $py -ArgumentList $watcher, "--channel", $Channel -WindowStyle Hidden
    Start-Sleep -Seconds 1
    Log "delivery watcher started channel=$Channel"
}

# Rider disabled: agent gateway + comfy_delivery_daemon are the only posters (no triple delivery).
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'roleplay-image-rider' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Log "stopped legacy image rider pid=$($_.ProcessId)"
    }