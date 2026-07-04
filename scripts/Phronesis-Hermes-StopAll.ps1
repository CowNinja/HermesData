# Stop every process that can lock hermes-agent\venv on Windows.
# Safe to run before update or venv rebuild.
param(
    [switch]$KeepPhronesisInference = $true,
    [switch]$Quiet = $false
)

$ErrorActionPreference = "Continue"
$HermesAgent = "D:\HermesData\hermes-agent"
$VenvMarker = "hermes-agent\venv"

function Log([string]$m) {
    if (-not $Quiet) { Write-Host $m }
}

Log "=== Phronesis Hermes Stop-All ==="

# Hermes CLI / gateway / dashboard / desktop backend
& "D:\HermesData\hermes-agent\venv\Scripts\hermes.exe" gateway stop 2>$null | Out-Null
Start-Sleep -Seconds 2

$patterns = @(
    'hermes_cli\.main gateway',
    'hermes_cli\.main dashboard',
    'hermes_cli\.main serve',
    'hermes-setup\.exe',
    'hermes-agent\.exe',
    'roleplay-image-rider',
    'sovereign_openai_proxy'
)

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = $_.CommandLine
    if (-not $cmd) { return }
    $kill = $false
    if ($cmd -like "*$VenvMarker*") { $kill = $true }
    foreach ($p in $patterns) {
        if ($cmd -match $p) { $kill = $true; break }
    }
    if ($cmd -match 'Hermes.*desktop|electron.*hermes' -or $_.Name -eq 'Hermes') { $kill = $true }
    if ($KeepPhronesisInference -and $cmd -match 'llama-server') { $kill = $false }
    if ($kill) {
        Log "  stop PID $($_.ProcessId) $($_.Name)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# Broad sweep for orphaned venv python(w) still holding .pyd locks
Get-Process python, pythonw, hermes, electron -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue
        if ($p.CommandLine -like "*$VenvMarker*") {
            Log "  stop orphan PID $($_.Id)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}

Start-Sleep -Seconds 2
Log "=== Stop-All complete ==="