# Phronesis-ForkGuard.ps1 v2 - venv-only enforcement for proxy, gateway, dashboard.
# Windows: venv python may delegate to a base-Python child; parent-chain walk = venv-owned.

param()

$corePath = Join-Path $PSScriptRoot "phronesis-core.json"
if (Test-Path $corePath) {
    $script:Core = Get-Content $corePath -Raw | ConvertFrom-Json
    $script:VenvPython = $core.venv_python
    $script:VenvMarker = $core.fork_guard.venv_marker
    $script:HermesRoot = if ($core.hermes_root) { $core.hermes_root } else { "D:\HermesData" }
} else {
    $script:VenvPython = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
    $script:VenvMarker = "hermes-agent\venv"
    $script:HermesRoot = "D:\HermesData"
}

$env:HERMES_HOME = $HermesRoot
$env:HERMES_CONFIG_PATH = Join-Path $HermesRoot "config.yaml"

$script:VenvPythonw = $VenvPython -replace 'python\.exe$', 'pythonw.exe'

function Get-PortListenerPid {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return $null
}

function Get-ProxyListenerPid {
    return Get-PortListenerPid -Port 8091
}

function Test-ProcessVenvChain {
    param([int]$ProcessId)
    return (Test-ProcessTreeMatches -ProcessId $ProcessId -RolePattern 'sovereign_openai_proxy' -RequireVenvInChain)
}

function Test-ProcessTreeMatches {
    param(
        [int]$ProcessId,
        [string]$RolePattern,
        [switch]$RequireVenvInChain
    )
    $walk = $ProcessId
    $sawRole = $false
    $sawVenv = $false
    for ($i = 0; $i -lt 10; $i++) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$walk" -ErrorAction SilentlyContinue
        if (-not $p -or -not $p.CommandLine) { break }
        if ($p.CommandLine -match $RolePattern) { $sawRole = $true }
        if ($p.CommandLine -like "*$VenvMarker*") { $sawVenv = $true }
        if (-not $p.ParentProcessId -or $p.ParentProcessId -eq $walk) { break }
        $walk = [int]$p.ParentProcessId
    }
    if (-not $sawRole) { return $false }
    if ($RequireVenvInChain) { return $sawVenv }
    return $true
}

function Test-VenvOwns8091 {
    $listenerPid = Get-PortListenerPid -Port 8091
    if (-not $listenerPid) { return $false }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 3
        if ($r.Content -notmatch 'GREEN|YELLOW') { return $false }
    } catch { return $false }
    return (Test-ProcessTreeMatches -ProcessId $listenerPid -RolePattern 'sovereign_openai_proxy' -RequireVenvInChain)
}

function Test-VenvOwnsGateway {
    $listenerPid = Get-PortListenerPid -Port $(if ($Core) { $Core.ports.gateway } else { 8642 })
    if (-not $listenerPid) { return $false }
    return (Test-ProcessTreeMatches -ProcessId $listenerPid -RolePattern 'hermes_cli\.main gateway run' -RequireVenvInChain)
}

function Test-VenvOwnsDashboard {
    $port = if ($Core -and $Core.ports.dashboard) { [int]$Core.ports.dashboard } else { 9119 }
    $listenerPid = Get-PortListenerPid -Port $port
    if (-not $listenerPid) { return $false }
    return (Test-ProcessTreeMatches -ProcessId $listenerPid -RolePattern 'hermes_cli\.main dashboard' -RequireVenvInChain)
}

function Test-GatewayHealth {
    $port = if ($Core) { $Core.ports.gateway } else { 8642 }
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 4
        return [bool]$r
    } catch { return $false }
}

function Test-HttpOk {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Stop-HermesProcesses {
    param([string]$RolePattern, [switch]$NonVenvOnly)
    $killed = @()
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $RolePattern } |
        ForEach-Object {
            $venvOk = Test-ProcessTreeMatches -ProcessId $_.ProcessId -RolePattern $RolePattern -RequireVenvInChain
            if ($NonVenvOnly -and $venvOk) { return }
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed += $_.ProcessId
        }
    return $killed
}

function Remove-SystemProxyForks {
    Stop-HermesProcesses -RolePattern 'sovereign_openai_proxy' -NonVenvOnly
}

function Remove-NonVenvGatewayDashboard {
    # Only kill processes whose parent chain lacks the venv marker.
    # Do NOT kill --replace gateways - venv python often spawns a base-Python
    # child that still owns the port with a venv parent (legitimate on Windows).
    $killed = @()
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -match 'hermes_cli\.main gateway run' -or
                $_.CommandLine -match 'hermes_cli\.main dashboard'
            )
        } |
        ForEach-Object {
            $role = if ($_.CommandLine -match 'gateway run') { 'hermes_cli\.main gateway run' } else { 'hermes_cli\.main dashboard' }
            $venvOk = Test-ProcessTreeMatches -ProcessId $_.ProcessId -RolePattern $role -RequireVenvInChain
            if (-not $venvOk) {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $killed += $_.ProcessId
            }
        }
    return $killed
}

function Get-GatewayPort {
    if ($Core) { return [int]$Core.ports.gateway }
    return 8642
}

function Remove-StaleGatewayZombies {
    # Kill gateway processes that are not the :8642 listener or its parent chain.
    $killed = @()
    $gwPort = Get-GatewayPort
    $listener = Get-PortListenerPid -Port $gwPort
    $keep = @{}
    if ($listener) {
        $walk = $listener
        for ($i = 0; $i -lt 12; $i++) {
            $keep[$walk] = $true
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$walk" -ErrorAction SilentlyContinue
            if (-not $p -or -not $p.ParentProcessId -or $p.ParentProcessId -eq $walk) { break }
            $walk = [int]$p.ParentProcessId
        }
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'hermes_cli\.main gateway run' } |
        ForEach-Object {
            if (-not $keep.ContainsKey([int]$_.ProcessId)) {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $killed += $_.ProcessId
            }
        }
    return $killed
}

function Set-HermesGatewayEnv {
    $env:HERMES_HOME = $HermesRoot
    $env:HERMES_CONFIG_PATH = Join-Path $HermesRoot "config.yaml"
    $env:HERMES_GATEWAY_RESPONSE_TRUNCATION_GUARD = "1"
    $env:HERMES_GATEWAY_FORCE_FINISH_REASON = "1"
}

function Wait-GatewayReady {
    param([int]$MaxSeconds = 45)
    $gwPort = Get-GatewayPort
    for ($i = 1; $i -le $MaxSeconds; $i++) {
        if ((Get-PortListenerPid -Port $gwPort) -and (Test-GatewayHealth) -and (Test-VenvOwnsGateway)) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Ensure-VenvProxyOnly {
    $killed = @(Remove-SystemProxyForks)
    if ((Get-PortListenerPid -Port 8091) -and -not (Test-VenvOwns8091)) {
        $rogue = Get-PortListenerPid -Port 8091
        if ($rogue) {
            Stop-Process -Id $rogue -Force -ErrorAction SilentlyContinue
            $killed += $rogue
        }
    }
    return $killed.Count
}

function Stop-NonVenvPortOwner {
    param([int]$Port, [string]$RolePattern)
    $killed = @()
    $listener = Get-PortListenerPid -Port $Port
    if (-not $listener) { return $killed }
    if (Test-ProcessTreeMatches -ProcessId $listener -RolePattern $RolePattern -RequireVenvInChain) {
        return $killed
    }
    Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
    $killed += $listener
    return $killed
}

function Ensure-VenvHermesOnly {
    $killed = @()
    $killed += @(Remove-SystemProxyForks)
    $killed += @(Stop-NonVenvPortOwner -Port 8091 -RolePattern 'sovereign_openai_proxy')
    $killed += @(Remove-NonVenvGatewayDashboard)
    $gwPort = if ($Core) { [int]$Core.ports.gateway } else { 8642 }
    $killed += @(Stop-NonVenvPortOwner -Port $gwPort -RolePattern 'hermes_cli\.main gateway run')
    $dashPort = if ($Core -and $Core.ports.dashboard) { [int]$Core.ports.dashboard } else { 9119 }
    $killed += @(Stop-NonVenvPortOwner -Port $dashPort -RolePattern 'hermes_cli\.main dashboard')
    return $killed.Count
}

function Wait-ProxyVenvReady {
    param([int]$MaxSeconds = 15)
    for ($i = 1; $i -le $MaxSeconds; $i++) {
        if (Test-VenvOwns8091) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-VenvGateway {
    Set-HermesGatewayEnv
    $pyw = if (Test-Path $VenvPythonw) { $VenvPythonw } else { $VenvPython }
    Start-Process -FilePath $pyw `
        -ArgumentList "-m", "hermes_cli.main", "gateway", "run" `
        -WorkingDirectory $HermesRoot `
        -WindowStyle Hidden
}

function Restart-VenvGateway {
    # Uses Hermes planned-stop markers - avoids ForkGuard/gateway startup races.
    Set-HermesGatewayEnv
    $pyw = if (Test-Path $VenvPythonw) { $VenvPythonw } else { $VenvPython }
    Start-Process -FilePath $pyw `
        -ArgumentList "-m", "hermes_cli.main", "gateway", "restart" `
        -WorkingDirectory $HermesRoot `
        -WindowStyle Hidden
}

function Start-VenvDashboard {
    $pyw = if (Test-Path $VenvPythonw) { $VenvPythonw } else { $VenvPython }
    $agentRoot = Join-Path $HermesRoot "hermes-agent"
    $webDist = Join-Path $agentRoot "hermes_cli\web_dist"
    $dashHost = "127.0.0.1"
    $dashPort = 9119
    if ($Core) {
        if ($Core.dashboard_host) { $dashHost = [string]$Core.dashboard_host }
        if ($Core.ports.dashboard) { $dashPort = [int]$Core.ports.dashboard }
    }
    $dashArgs = @("-m", "hermes_cli.main", "dashboard", "--port", "$dashPort", "--host", $dashHost, "--no-open")
    if (Test-Path (Join-Path $webDist "index.html")) {
        $dashArgs += "--skip-build"
    }
    Start-Process -FilePath $pyw `
        -ArgumentList $dashArgs `
        -WorkingDirectory $agentRoot `
        -WindowStyle Hidden
}

function Start-WorkspaceServer {
    $node = if ($Core -and $Core.node_exe) { $Core.node_exe } else { "node.exe" }
    $wsDir = if ($Core -and $Core.workspace_dir) { $Core.workspace_dir } else { "D:\HermesData\hermes-workspace" }
    if (-not (Test-Path (Join-Path $wsDir "server-entry.js"))) { return $false }
    Start-Process -FilePath $node `
        -ArgumentList "server-entry.js" `
        -WorkingDirectory $wsDir `
        -WindowStyle Hidden
    return $true
}

function Wait-PortUp {
    param([int]$Port, [int]$MaxSeconds = 20)
    for ($i = 1; $i -le $MaxSeconds; $i++) {
        if (Get-PortListenerPid -Port $Port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}