# run-model-management-agent.ps1 - PS-pipe-safe entry for model management agent
param(
    [switch]$Tick,
    [switch]$FullTick,
    [switch]$DryRun,
    [switch]$BenchmarkActive,
    [switch]$Remediate,
    [switch]$Summary,
    [switch]$NoSummary
)

$ErrorActionPreference = "Stop"
$Scripts = Split-Path -Parent $MyInvocation.MyCommand.Path
$CoreJson = Join-Path $Scripts "phronesis-core.json"
$Python = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
if (Test-Path $CoreJson) {
    try {
        $core = Get-Content $CoreJson -Raw | ConvertFrom-Json
        if ($core.venv_python) { $Python = $core.venv_python }
    } catch {
        # keep default venv path
    }
}
$Agent = Join-Path $Scripts "model_management_agent.py"

if (-not (Test-Path $Python)) {
    Write-Error "Hermes venv python not found at $Python (check phronesis-core.json venv_python)"
}
if (-not (Test-Path $Agent)) {
    Write-Error "Agent script not found at $Agent"
}

$agentArgs = @()
if ($FullTick) { $agentArgs += "--full-tick" }
elseif ($Tick -or -not $BenchmarkActive) { $agentArgs += "--tick" }
if ($DryRun) { $agentArgs += "--dry-run" }
if ($Remediate) { $agentArgs += "--remediate" }
# Default --summary for tick modes (PS-pipe-safe); opt out with -NoSummary
$wantSummary = $Summary -or ((-not $NoSummary) -and ($FullTick -or $Tick -or (-not $BenchmarkActive)))
if ($wantSummary) { $agentArgs += "--summary" }
if ($BenchmarkActive) { $agentArgs = @("--benchmark-active") }

& $Python $Agent @agentArgs
exit $LASTEXITCODE