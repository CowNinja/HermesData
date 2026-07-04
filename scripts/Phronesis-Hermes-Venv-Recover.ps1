# Rebuild hermes-agent venv after a bricked update.
# Custom Phronesis work (config.yaml, plugins/, skills/) lives OUTSIDE venv - preserved automatically.
# venv.old is archival only (June 2026 snapshot) - NOT used for restore.
param(
    [switch]$SkipStop = $false,
    [switch]$KeepBrokenVenv = $true
)

$ErrorActionPreference = "Stop"
$HermesAgent = "D:\HermesData\hermes-agent"
$Uv = "D:\HermesData\bin\uv.exe"
$LogDir = "D:\HermesData\logs"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $LogDir "venv-recover-$Stamp.log"

function Log([string]$m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') | $m"
    Write-Host $line
    Add-Content -Path $Log -Value $line
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Log "=== Hermes venv recovery started ==="

if (-not $SkipStop) {
    & (Join-Path $PSScriptRoot "Phronesis-Hermes-StopAll.ps1")
}

Set-Location $HermesAgent
$env:UV_PROJECT_ENVIRONMENT = Join-Path $HermesAgent "venv"

if (-not (Test-Path $Uv)) {
    throw "uv not found at $Uv"
}

# Archive broken venv (do not delete venv.old - user archival from June 18)
if (Test-Path "venv") {
    $brokenName = if ($KeepBrokenVenv) { "venv.broken-$Stamp" } else { $null }
    if ($brokenName) {
        Log "Archiving broken venv -> $brokenName"
        if (Test-Path $brokenName) { Remove-Item -Recurse -Force $brokenName }
        Rename-Item -Path "venv" -NewName $brokenName -Force
    } else {
        Log "Removing broken venv"
        Remove-Item -Recurse -Force "venv" -ErrorAction Stop
    }
}

# Remove sibling .venv if uv synced there by mistake
if (Test-Path ".venv") {
    Log "Removing stray .venv"
    Remove-Item -Recurse -Force ".venv"
}

Log "Creating fresh venv (Python 3.11)"
& $Uv venv venv --python 3.11 --seed
if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }

$py = Join-Path $HermesAgent "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python missing after uv venv: $py" }

$tiers = @(".[all]", ".", ".[web]")
$installed = $false
foreach ($spec in $tiers) {
    Log "uv pip install --python $py -e $spec"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Uv pip install --python $py -e $spec 2>&1 | ForEach-Object { Log "  $_" }
    $tierExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($tierExit -eq 0) {
        $installed = $true
        Log "Installed tier: $spec"
        break
    }
    Log "WARN tier failed: $spec (exit $tierExit)"
}
if (-not $installed) { throw "All install tiers failed - see $Log" }

Log "Verifying baseline imports"
& $py -c "import dotenv, openai, rich, prompt_toolkit, aiohttp; print('baseline OK', aiohttp.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Baseline import check failed" }

& $py -c "import hermes_cli; print('hermes_cli OK')"
if ($LASTEXITCODE -ne 0) { throw "hermes_cli import failed" }

Log "Re-enabling plugins (config.yaml plugins.enabled)"
& $py -m hermes_cli.main plugins list 2>&1 | Out-Null

Log "=== Recovery complete ==="
Log "Next: hermes gateway restart; then Phronesis-OneButton-Start.ps1"
Write-Host ""
Write-Host "Log: $Log" -ForegroundColor Cyan