# Kill orphan Comfy main.py processes that are not listening on :8188.
# Keeps the healthy listener; removes zombie spawns from hybrid warm races.
param(
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

function Get-ComfyMainProcs {
    return @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'ComfyUI\\main\.py' })
}

function Get-InferenceListenerPids {
    return @(Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
}

$listeners = Get-InferenceListenerPids
$procs = Get-ComfyMainProcs
$killed = @()
$httpHealthy = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 4 | Out-Null
    $httpHealthy = $true
} catch {}

# If HTTP is healthy but port enum missed listener, do not kill any main.py.
if ($httpHealthy -and $listeners.Count -eq 0 -and $procs.Count -gt 0) {
    Log "Comfy HTTP healthy - skip orphan kill (listener enum lag)"
    $procs = @()
}

foreach ($proc in $procs) {
    if ($listeners -contains $proc.ProcessId) { continue }
    if ($httpHealthy -and $listeners.Count -eq 0) { continue }
    if ($listeners.Count -eq 0) { continue }
    Log "stop orphan Comfy main.py pid=$($proc.ProcessId)"
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    $killed += $proc.ProcessId
}

# Re-check: never leave inference without a listener when HTTP was healthy before repair.
if ($httpHealthy) {
    Start-Sleep -Seconds 2
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 4 | Out-Null
    } catch {
        if ($listeners.Count -gt 0) {
            Log "Comfy HTTP lost after repair - skip further kills"
        }
    }
}

if ($listeners.Count -gt 1) {
    $extras = $listeners | Select-Object -Skip 1
    foreach ($extraPid in $extras) {
        Log "stop duplicate :8188 listener pid=$extraPid"
        Stop-Process -Id $extraPid -Force -ErrorAction SilentlyContinue
        $killed += $extraPid
    }
}

if ($killed.Count -gt 0) { Start-Sleep -Seconds 2 }

@{
    killed          = $killed
    listener_pids   = $listeners
    main_py_count   = $procs.Count
    listener_count  = $listeners.Count
} | ConvertTo-Json -Depth 4