# 05-heal-dashboard.ps1 - restart Hermes CLI dashboard on :9119 (optional ops surface)
$ErrorActionPreference = "SilentlyContinue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "..\Phronesis-ForkGuard.ps1")

$corePath = Join-Path $scriptRoot "..\phronesis-core.json"
$dashPort = 9119
# Loopback bind for reliable local heal -- 0.0.0.0 from core can leave zombie forks without HTTP.
$dashHost = "127.0.0.1"
if (Test-Path $corePath) {
    try {
        $core = Get-Content $corePath -Raw | ConvertFrom-Json
        if ($core.ports.dashboard) { $dashPort = [int]$core.ports.dashboard }
    } catch {
        # keep default
    }
}

$env:HERMES_QUIET_SECRETS = '1'
Remove-NonVenvGatewayDashboard | Out-Null
Stop-HermesProcesses -RolePattern 'hermes_cli.main dashboard' | Out-Null
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'hermes_cli\.main dashboard' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$staleListener = Get-PortListenerPid -Port $dashPort
if ($staleListener -and -not (Test-VenvOwnsDashboard)) {
    Stop-Process -Id $staleListener -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

$agentRoot = Join-Path $HermesRoot "hermes-agent"
$webDist = Join-Path $agentRoot "hermes_cli\web_dist\index.html"
if (-not (Test-Path $webDist)) {
    Write-Host "Building Hermes web UI (web_dist missing)..."
    Push-Location $agentRoot
    npm.cmd run build -w web 2>&1 | ForEach-Object { Write-Host $_ }
    Pop-Location
}

function Test-DashboardHttp {
    param([int]$Port)
    return (Test-HttpOk -Url "http://127.0.0.1:$Port/api/status")
}

# pythonw hidden first (ForkGuard default); python.exe hidden fallback if HTTP slow
Start-VenvDashboard
$up = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (Test-DashboardHttp -Port $dashPort) { $up = $true; break }
}
if (-not $up) {
    $py = if (Test-Path $VenvPython) { $VenvPython } else { $VenvPythonw }
    $dashArgs = @("-m", "hermes_cli.main", "dashboard", "--port", "$dashPort", "--host", $dashHost, "--no-open")
    if (Test-Path $webDist) { $dashArgs += "--skip-build" }
    Start-Process -FilePath $py `
        -ArgumentList $dashArgs `
        -WorkingDirectory $agentRoot `
        -WindowStyle Hidden
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 1
        if (Test-DashboardHttp -Port $dashPort) { $up = $true; break }
    }
}
if ($up) {
    Write-Host "CLI dashboard listening on :$dashPort (api/status OK)"
    exit 0
}
Write-Host "CLI dashboard failed to bind :$dashPort within timeout"
exit 1