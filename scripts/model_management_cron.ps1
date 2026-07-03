# model_management_cron.ps1 — scheduled agent ticks (6h light / 24h full)
param(
    [ValidateSet("light", "full")]
    [string]$Mode = "light"
)

$ErrorActionPreference = "Stop"
$wrapper = Join-Path $PSScriptRoot "run-model-management-agent.ps1"

if ($Mode -eq "full") {
    & $wrapper -FullTick
} else {
    & $wrapper -Tick
}
exit $LASTEXITCODE