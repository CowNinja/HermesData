# Phronesis-Heal.ps1 - Shared auto-heal engine (Guardian + manual heal use this)
param(
    [switch]$ForceGateway,
    [switch]$Quiet
)

$ErrorActionPreference = "SilentlyContinue"
$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

. (Join-Path $scriptRoot "Phronesis-Session.ps1")
. (Join-Path $scriptRoot "Phronesis-ForkGuard.ps1")
. (Join-Path $scriptRoot "Phronesis-Maintenance-Lock.ps1")

$corePath = Join-Path $scriptRoot "phronesis-core.json"
$core = Get-Content $corePath -Raw | ConvertFrom-Json
$session = Get-PhronesisSession
$log = Join-Path $core.log_dir "guardian.log"
New-Item -ItemType Directory -Force -Path $core.log_dir | Out-Null

$actions = @()

function Port-Up([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Write-Heal([string]$m, [string]$color = "Gray") {
    if (-not $Quiet) { Write-Host $m -ForegroundColor $color }
}

# ForkGuard - kill non-venv Hermes forks
$fk = Ensure-VenvHermesOnly
if ($fk -gt 0) { $actions += "forkguard:$fk"; Write-Heal "ForkGuard removed $fk non-venv process(es)" "Yellow" }

# Max 1 llama-server
$llamas = @(Get-Process -Name llama-server -ErrorAction SilentlyContinue)
if ($llamas.Count -gt 1) {
    $llamas | Select-Object -Skip 1 | Stop-Process -Force
    $actions += "kill_extra_llama:$($llamas.Count - 1)"
    Write-Heal "Killed $($llamas.Count - 1) duplicate llama-server" "Yellow"
}

# Inference 8090/8091
$needInference = $false
if (-not (Port-Up $core.ports.router)) { $needInference = $true; $actions += "8090:DOWN" }
if (-not (Port-Up $core.ports.proxy)) { $needInference = $true; $actions += "8091:DOWN" }
if ((Port-Up $core.ports.proxy) -and -not (Test-VenvOwns8091)) {
    $needInference = $true; $actions += "8091:NOT_VENV"
}

if ($needInference) {
    Start-Sleep -Seconds 2
    Write-Heal "Healing inference (8090/8091)..." "Cyan"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "Phronesis-OneButton-Start.ps1") -SkipGateway -SkipDashboard -SkipWorkspace -SkipSmoke
    $actions += "onebutton_inference"
}

# Gateway
$port8642 = "SKIP"
if ($core.start_gateway) {
    $gwPort = [int]$core.ports.gateway
    $hermesRoot = if ($core.hermes_root) { $core.hermes_root } else { "D:\HermesData" }
    $healMarker = Join-Path $hermesRoot "gateway\.last_heal"
    $healCooldownSec = 90

    $gwDown = -not (Port-Up $gwPort)
    $gwBadOwner = (Port-Up $gwPort) -and -not (Test-VenvOwnsGateway)
    $gwUnhealthy = (Port-Up $gwPort) -and -not (Test-GatewayHealth)

    $inCooldown = $false
    if (-not $ForceGateway -and (Test-Path $healMarker)) {
        $lastHeal = (Get-Item $healMarker).LastWriteTime
        if (((Get-Date) - $lastHeal).TotalSeconds -lt $healCooldownSec) { $inCooldown = $true }
    }

    $gwBlock = Test-PhronesisMaintenanceBlocked -Action gateway_heal
    if (($gwDown -or $gwBadOwner -or $gwUnhealthy) -and -not $inCooldown -and -not $gwBlock.blocked) {
        Write-Heal "Healing gateway ($gwPort)..." "Cyan"
        $zombies = @(Remove-StaleGatewayZombies)
        if ($zombies.Count -gt 0) { $actions += "gw_zombies:$($zombies.Count)" }

        if ($gwBadOwner) {
            $killed = @(Stop-HermesProcesses -RolePattern 'hermes_cli\.main gateway run' -NonVenvOnly)
            if ($killed.Count -gt 0) { $actions += "gateway_kill_nonvenv:$($killed.Count)" }
            Start-Sleep -Seconds 2
        }

        & $core.venv_python (Join-Path $scriptRoot "sovereign_preflight.py") 2>$null

        $restartBlock = Test-PhronesisMaintenanceBlocked -Action gateway_restart
        if ($gwDown) { Start-VenvGateway; $actions += "gateway_start" }
        elseif (-not $restartBlock.blocked) { Restart-VenvGateway; $actions += "gateway_restart" }
        else { $actions += "gateway_restart:LOCKED"; Write-Heal "Gateway restart skipped (maintenance lock / in-flight Discord)" "DarkYellow" }

        New-Item -ItemType Directory -Force -Path (Split-Path $healMarker) | Out-Null
        Set-Content -Path $healMarker -Value (Get-Date -Format 'o') -NoNewline

        if (Wait-GatewayReady -MaxSeconds 45) {
            $actions += if (Test-VenvOwnsGateway) { "gateway_heal:OK" } else { "gateway_heal:NOT_VENV" }
        } else {
            $actions += "gateway_heal:FAIL"
        }
    } elseif (($gwDown -or $gwBadOwner -or $gwUnhealthy) -and $gwBlock.blocked) {
        $actions += "gateway_heal:LOCKED"
        Write-Heal "Gateway heal skipped ($($gwBlock.reason))" "DarkYellow"
    } elseif (($gwDown -or $gwBadOwner -or $gwUnhealthy) -and $inCooldown) {
        $actions += "gateway_heal:COOLDOWN"
        Write-Heal "Gateway heal skipped (90s cooldown - use 'heal -ForceGateway')" "DarkYellow"
    }

    $port8642 = if (Port-Up $gwPort) { "UP" } else { "DOWN" }
}

# Dashboard
$port9119 = "SKIP"
if ($core.start_dashboard) {
    $dashPort = [int]$core.ports.dashboard
    $needDash = (-not (Port-Up $dashPort)) -or -not (Test-VenvOwnsDashboard)
    if ($needDash) {
        Write-Heal "Healing dashboard ($dashPort) via 05-heal-dashboard.ps1..." "Cyan"
        $healDashPs1 = Join-Path $scriptRoot "ops\05-heal-dashboard.ps1"
        if (Test-Path $healDashPs1) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $healDashPs1 | Out-Null
            if ($LASTEXITCODE -eq 0 -and (Wait-PortUp -Port $dashPort -MaxSeconds 10)) {
                $actions += "dashboard_restart:OK"
            } else {
                $actions += "dashboard_restart:FAIL"
            }
        } else {
            Stop-HermesProcesses -RolePattern 'hermes_cli\.main dashboard' | Out-Null
            Start-VenvDashboard
            if (Wait-PortUp -Port $dashPort -MaxSeconds 35) { $actions += "dashboard_restart:OK" }
            else { $actions += "dashboard_restart:FAIL" }
        }
    }
    $port9119 = if (Port-Up $dashPort) { "UP" } else { "DOWN" }
}

# Workspace
$port3001 = "SKIP"
if ($core.start_workspace) {
    $wsPort = [int]$core.ports.workspace
    if (-not (Port-Up $wsPort)) {
        Write-Heal "Healing workspace ($wsPort)..." "Cyan"
        if (Start-WorkspaceServer) {
            if (Wait-PortUp -Port $wsPort -MaxSeconds 25) { $actions += "workspace_restart:OK" }
            else { $actions += "workspace_restart:FAIL" }
        }
    }
    $port3001 = if (Port-Up $wsPort) { "UP" } else { "DOWN" }
}

$port8090 = if (Port-Up $core.ports.router) { "UP" } else { "DOWN" }
$port8091 = if (Port-Up $core.ports.proxy) { "UP" } else { "DOWN" }
$llamaCount = @(Get-Process -Name llama-server -ErrorAction SilentlyContinue).Count
$venvProxy = Test-VenvOwns8091
$venvGw = if ($core.start_gateway) { Test-VenvOwnsGateway } else { $true }
$venvDash = if ($core.start_dashboard) { Test-VenvOwnsDashboard } else { $true }

$healthy = ($port8090 -eq "UP" -and $port8091 -eq "UP" -and $llamaCount -le 1 -and $venvProxy -and $venvGw -and $venvDash)
if ($core.start_gateway) { $healthy = $healthy -and ($port8642 -eq "UP") -and (Test-GatewayHealth) }
if ($core.start_dashboard) { $healthy = $healthy -and ($port9119 -eq "UP") }
if ($core.start_workspace) { $healthy = $healthy -and ($port3001 -eq "UP") }

$status = if ($healthy) { "healthy" } else { "DEGRADED" }
$actStr = if ($actions.Count -eq 0) { "NONE" } else { $actions -join "|" }
$portStr = "8090=$port8090 8091=$port8091 8642=$port8642 9119=$port9119 3001=$port3001 venv_proxy=$venvProxy venv_gw=$venvGw venv_dash=$venvDash"
$line = "Session $session $status | $portStr | $llamaCount llama | $actStr"
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $line" | Out-File -Append -FilePath $log

if ($status -eq "DEGRADED" -or $actStr -ne "NONE") {
    Write-SessionHealthLog "$status | $actStr | heal auto-append"
}

if (-not $Quiet) {
    $color = if ($healthy) { "Green" } else { "Yellow" }
    Write-Heal "`n$status | $portStr | actions=$actStr" $color
}

[PSCustomObject]@{
    Healthy  = $healthy
    Status   = $status
    Actions  = $actStr
    Ports    = $portStr
    ExitCode = if ($healthy) { 0 } else { 1 }
}