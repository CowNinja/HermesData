# Start Phronesis MoE stack — unified LRU router (8090) or legacy static 808x
# Usage:
#   D:\HermesData\scripts\Start-MoE-Stack.ps1                 # unified 8090 (default P2)
#   D:\HermesData\scripts\Start-MoE-Stack.ps1 -Legacy808x   # rollback to static ports
#   D:\HermesData\scripts\Start-MoE-Stack.ps1 -Unified8090 -ModelsMax 4

param(
    [switch]$Legacy808x,
    [switch]$Unified8090,
    [switch]$SkipWarm,
    [int]$ModelsMax = 0
)

$ErrorActionPreference = "Continue"
$scriptDir = $PSScriptRoot

if ($Legacy808x) {
    $Unified8090 = $false
} elseif (-not $PSBoundParameters.ContainsKey("Unified8090")) {
    $Unified8090 = $true
}

Write-Host "=== Phronesis MoE Stack Start ===" -ForegroundColor Cyan

if ($Unified8090) {
    Write-Host "Mode: UNIFIED LRU router @ 8090" -ForegroundColor Green
    $stopStatic = Join-Path $scriptDir "Stop-Static-MoE-Ports.ps1"
    if (Test-Path $stopStatic) {
        & $stopStatic
    }
    $unified = Join-Path $scriptDir "Start-Unified-Router-8090.ps1"
    if (-not (Test-Path $unified)) {
        Write-Host "Missing $unified" -ForegroundColor Red
        exit 1
    }
    $args = @{}
    if ($ModelsMax -gt 0) { $args.ModelsMax = $ModelsMax }
    & $unified @args
} else {
    Write-Host "Mode: LEGACY static 8081/8082/8083" -ForegroundColor Yellow
    $start = "D:\PhronesisVault\tests\Start-SovereignServers.ps1"
    if (-not (Test-Path $start)) {
        Write-Host "Missing $start" -ForegroundColor Red
        exit 1
    }
    Write-Host "Hot 8081: Qwen2.5-Coder-3B (daily driver)"
    Write-Host "Classifier 8083: gemma-2-2b"
    if (-not $SkipWarm) {
        Write-Host "Warm 8082: Qwen2.5-7B-Instruct-Q5_K_M (on demand)"
    }
    & $start -Daily -Classifier
    if (-not $SkipWarm) {
        & $start -Test -Model "Qwen2.5-7B-Instruct-Q5_K_M.gguf" -CtxSize 12288 -Parallel 1
    }
    Start-Sleep -Seconds 10
}

# Agent gateway (Hermes primary loop → bridge_dispatch)
$proxyScript = Join-Path $scriptDir "Start-Sovereign-Proxy-8091.ps1"
if (Test-Path $proxyScript) {
    & $proxyScript
}

$checkPorts = if ($Unified8090) { @(8090, 8091) } else { @(8081, 8082, 8083, 8091) }
foreach ($p in $checkPorts) {
    try {
        $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $p -WarningAction SilentlyContinue
        $ok = $r.TcpTestSucceeded
        Write-Host ("Port {0}: {1}" -f $p, $(if ($ok) { "UP" } else { "DOWN" })) -ForegroundColor $(if ($ok) { "Green" } else { "Yellow" })
    } catch {
        Write-Host "Port $p : ERROR" -ForegroundColor Red
    }
}

$watchdogScript = Join-Path $scriptDir "Start-Sovereign-Watchdog.ps1"
if (Test-Path $watchdogScript) {
    & $watchdogScript
}

if ($Unified8090) {
    Write-Host ""
    Write-Host "Unified LRU MoE ready @ 8090. Router picks logical model per task." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Legacy MoE ready. Router picks tier per task via sovereign_router.py" -ForegroundColor Green
}
