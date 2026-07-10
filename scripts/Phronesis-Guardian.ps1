# Phronesis-Guardian.ps1 - Scheduled health pass (every 5 min). Heal + travel comms lane.
$ErrorActionPreference = "SilentlyContinue"
$root = if ($PSScriptRoot) { $PSScriptRoot } else { "D:\HermesData\scripts" }
$hermesRoot = "D:\HermesData"
$py = Join-Path $hermesRoot "hermes-agent\venv\Scripts\python.exe"

. (Join-Path $root "Phronesis-Maintenance-Lock.ps1")
$block = Test-PhronesisMaintenanceBlocked -Action stack_heal
if ($block.blocked) { exit 0 }

$result = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "Phronesis-Heal.ps1") -Quiet

# Travel lane: Grok direct bridge + inbox consumer + heartbeat (6h gate) + dashboard health
$ensureBridge = Join-Path $hermesRoot "scripts\ops\Ensure-Grok-Direct-Bridge.ps1"
if (Test-Path $ensureBridge) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ensureBridge -Quiet | Out-Null
}
if (Test-Path $py) {
    $inbox = Join-Path $hermesRoot "scripts\grok_inbox_consumer.py"
    $heartbeat = Join-Path $hermesRoot "scripts\grok_direct_heartbeat.py"
    $health = Join-Path $hermesRoot "scripts\phronesis_fullstack_health.py"
    if (Test-Path $inbox) { & $py $inbox --once 2>$null | Out-Null }
    if (Test-Path $heartbeat) { & $py $heartbeat --tick 2>$null | Out-Null }
    if (Test-Path $health) { & $py $health 2>$null | Out-Null }
}

exit $(if ($result -and $result.ExitCode -ne $null) { $result.ExitCode } else { 0 })