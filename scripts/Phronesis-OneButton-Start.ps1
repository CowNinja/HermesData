# Phronesis-OneButton-Start.ps1 - THE ONLY script you need to start Phronesis.
# Starts: 8090 (brain) + 8091 (translator) + 8642 (Hermes gateway, optional).
# Usage:  powershell -File D:\HermesData\scripts\Phronesis-OneButton-Start.ps1
#         powershell -File ... -SkipGateway   (inference only)

param(
    [switch]$SkipGateway = $false,
    [switch]$SkipDashboard = $false,
    [switch]$SkipWorkspace = $false,
    [switch]$SkipSmoke = $false
)

$ErrorActionPreference = "Continue"
$corePath = Join-Path $PSScriptRoot "phronesis-core.json"
if (-not (Test-Path $corePath)) { Write-Host "FATAL: phronesis-core.json missing" -ForegroundColor Red; exit 1 }
$core = Get-Content $corePath -Raw | ConvertFrom-Json

. (Join-Path $PSScriptRoot "Phronesis-ForkGuard.ps1")

$py = $core.venv_python
$logDir = $core.log_dir
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "onebutton-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"

function Log([string]$m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') | $m"
    Write-Host $line
    Add-Content -Path $log -Value $line
}

function Port-Up([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Get-VramFreeMb {
    $out = nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>$null
    if ($out) { return [int]($out.Trim()) }
    return 99999
}

function Get-LoadedModelPath {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$($core.ports.router)/v1/models" -TimeoutSec 3
        return $resp.models[0].name
    } catch { return $null }
}

function Resolve-ModelConfig {
    $model = $core.model
    $ctx = [int]$core.ctx_size
    $ngl = [int]$core.n_gpu_layers
    $free = Get-VramFreeMb
    $minFree = [int]$core.vram.min_free_mb
    if ($core.model_locked -or $core.model_rotation_locked) {
        if ($free -lt $minFree) { Log "VRAM WARN: ${free}MB free < ${minFree}MB (rotation locked - keeping Qwythos 9B)" }
        return @{ Model = $model; Ctx = $ctx; Ngl = $ngl; VramFree = $free }
    }
    if ($free -lt $minFree -and $core.vram.fallback_model) {
        Log "VRAM WARN: ${free}MB free < ${minFree}MB - using fallback model"
        $model = $core.vram.fallback_model
        $ctx = [int]$core.vram.fallback_ctx_size
        $ngl = [int]$core.vram.fallback_n_gpu_layers
    }
    return @{ Model = $model; Ctx = $ctx; Ngl = $ngl; VramFree = $free }
}

Log "=== Phronesis One-Button Start ==="

# --- ForkGuard FIRST (proxy + gateway + dashboard venv enforcement) ---
$forkKills = Ensure-VenvHermesOnly
if ($forkKills -gt 0) { Log "ForkGuard: removed $forkKills non-venv Hermes process(es)" }

# --- Dedup: one llama ---
$llamas = @(Get-Process -Name llama-server -ErrorAction SilentlyContinue)
if ($llamas.Count -gt 1) {
    $llamas | Select-Object -Skip 1 | Stop-Process -Force
    Log "Killed $($llamas.Count - 1) duplicate llama-server"
}

# Stop wrong model BEFORE VRAM check so 9B can load
$preferred = $core.model
if (Port-Up $core.ports.router) {
    $loaded = Get-LoadedModelPath
    if ($loaded -and $loaded -ne $preferred) {
        Log "Model swap: stopping 8090 ($(Split-Path $loaded -Leaf) -> $(Split-Path $preferred -Leaf))"
        Get-Process -Name llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 4
    }
}

$mc = Resolve-ModelConfig
Log "Model target: $(Split-Path $mc.Model -Leaf) ctx=$($mc.Ctx) VRAM free=$($mc.VramFree)MB"

# --- 8090 Router (brain) ---
$need8090 = -not (Port-Up $core.ports.router)

if ($need8090) {
    Log "Starting llama-server on $($core.ports.router)..."
    if (-not (Test-Path $core.llama_exe)) { Log "FATAL: llama-server not found"; exit 1 }
    if (-not (Test-Path $mc.Model)) { Log "FATAL: model not found"; exit 1 }
    $args = @(
        "--model", $mc.Model,
        "--host", "127.0.0.1",
        "--port", "$($core.ports.router)",
        "--ctx-size", "$($mc.Ctx)",
        "--n-gpu-layers", "$($mc.Ngl)",
        "--parallel", "1",
        "--cont-batching",
        "--flash-attn", "on"
    )
    Start-Process -FilePath $core.llama_exe -ArgumentList $args -WindowStyle Hidden
    $ready = $false
    for ($i = 1; $i -le 120; $i++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$($core.ports.router)/v1/models" -TimeoutSec 2 | Out-Null
            $ready = $true; break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { Log "FATAL: 8090 did not become ready"; exit 1 }
    Log "8090 UP"
} else { Log "8090 already UP (correct model)" }

# --- 8091 Proxy (venv python.exe only - Wait-ProxyVenvReady) ---
Ensure-VenvProxyOnly | Out-Null
if (-not (Test-VenvOwns8091)) {
    if (Port-Up $core.ports.proxy) { Log "8091 not venv-owned - recycling..." }
    else { Log "Starting sovereign proxy on $($core.ports.proxy)..." }
    Stop-HermesProcesses -RolePattern 'sovereign_openai_proxy' | Out-Null
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "Start-Sovereign-Proxy-8091.ps1")
    if (-not (Wait-ProxyVenvReady -MaxSeconds 15)) {
        Log "FATAL: 8091 did not start under venv (parent-chain timeout)"
        exit 1
    }
    Log "8091 UP (venv-owned)"
} else { Log "8091 already UP (venv-owned)" }

# --- 8642 Gateway (venv pythonw only; never kill venv-owned) ---
if (-not $SkipGateway -and $core.start_gateway) {
    $gwPort = [int]$core.ports.gateway
    $gwDown = -not (Port-Up $gwPort)
    $gwBadOwner = (Port-Up $gwPort) -and -not (Test-VenvOwnsGateway)
    $gwUnhealthy = (Port-Up $gwPort) -and -not (Test-GatewayHealth)
    if ($gwDown -or $gwBadOwner -or $gwUnhealthy) {
        $zombies = @(Remove-StaleGatewayZombies)
        if ($zombies.Count -gt 0) { Log "Removed $($zombies.Count) stale gateway zombie(s)" }
        if ($gwBadOwner) {
            $killed = @(Stop-HermesProcesses -RolePattern 'hermes_cli\.main gateway run' -NonVenvOnly)
            if ($killed.Count -gt 0) { Log "Killed $($killed.Count) non-venv gateway process(es)" }
            Start-Sleep -Seconds 2
        }
        Log "8091 preflight before gateway..."
        & $py (Join-Path $PSScriptRoot "sovereign_preflight.py") 2>$null
        if ($gwDown) { Start-VenvGateway; Log "Starting gateway on $gwPort..." }
        else { Restart-VenvGateway; Log "Restarting gateway on $gwPort (planned stop)..." }
        if (Wait-GatewayReady -MaxSeconds 45) { Log "8642 UP (venv-owned, healthy)" }
        else { Log "WARN: 8642 not ready within 45s" }
    } else { Log "8642 already UP (venv-owned, healthy)" }
}

# --- 9119 Dashboard (venv pythonw only) ---
if (-not $SkipDashboard -and $core.start_dashboard) {
    $dashPort = [int]$core.ports.dashboard
    $needDash = (-not (Port-Up $dashPort)) -or -not (Test-VenvOwnsDashboard)
    if ($needDash) {
        Log "Starting Hermes dashboard on $dashPort (venv)..."
        Stop-HermesProcesses -RolePattern 'hermes_cli\.main dashboard' | Out-Null
        Start-VenvDashboard
        if (Wait-PortUp -Port $dashPort -MaxSeconds 20) { Log "$dashPort UP (venv-owned)" }
        else { Log "WARN: $dashPort not listening" }
    } else { Log "$dashPort already UP (venv-owned)" }
}

# --- 3001 Workspace (node) ---
if (-not $SkipWorkspace -and $core.start_workspace) {
    $wsPort = [int]$core.ports.workspace
    if (-not (Port-Up $wsPort)) {
        Log "Starting Hermes workspace on $wsPort..."
        if (Start-WorkspaceServer) {
            if (Wait-PortUp -Port $wsPort -MaxSeconds 25) { Log "$wsPort UP" }
            else { Log "WARN: $wsPort not listening" }
        }
    } else { Log "$wsPort already UP" }
}

# --- Verify ---
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ops\04-status.ps1")
if (-not $SkipSmoke) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ops\06-smoke-test.ps1")
    if ($LASTEXITCODE -ne 0) { Log "Smoke test FAILED"; exit 1 }
}
Log "=== DONE - Phronesis is ready ==="