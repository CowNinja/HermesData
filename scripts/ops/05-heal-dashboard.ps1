# 05-heal-dashboard.ps1 - restart Hermes CLI dashboard on :9119 (optional ops surface)
$ErrorActionPreference = "SilentlyContinue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "..\Phronesis-ForkGuard.ps1")

$corePath = Join-Path $scriptRoot "..\phronesis-core.json"
$dashPort = 9119
$dashHost = "127.0.0.1"
if (Test-Path $corePath) {
    try {
        $core = Get-Content $corePath -Raw | ConvertFrom-Json
        if ($core.ports.dashboard) { $dashPort = [int]$core.ports.dashboard }
        if ($core.dashboard_host) { $dashHost = [string]$core.dashboard_host }
    } catch {
        # keep default
    }
}

Stop-HermesProcesses -RolePattern 'hermes_cli.main dashboard' | Out-Null
Start-Sleep -Seconds 2

$agentRoot = Join-Path $HermesRoot "hermes-agent"
$webDist = Join-Path $agentRoot "hermes_cli\web_dist\index.html"
if (-not (Test-Path $webDist)) {
    Write-Host "Building Hermes web UI (web_dist missing)..."
    Push-Location $agentRoot
    npm.cmd run build -w web 2>&1 | ForEach-Object { Write-Host $_ }
    Pop-Location
}

# pythonw hidden first (ForkGuard default); python.exe hidden fallback if port slow
Start-VenvDashboard
$up = Wait-PortUp -Port $dashPort -MaxSeconds 30
if (-not $up) {
    $py = if (Test-Path $VenvPython) { $VenvPython } else { $VenvPythonw }
    Start-Process -FilePath $py `
        -ArgumentList "-m", "hermes_cli.main", "dashboard", "--port", "$dashPort", "--host", $dashHost, "--skip-build", "--no-open" `
        -WorkingDirectory $HermesRoot `
        -WindowStyle Hidden
    $up = Wait-PortUp -Port $dashPort -MaxSeconds 35
}
if ($up) {
    Write-Host "CLI dashboard listening on :$dashPort"
    exit 0
}
Write-Host "CLI dashboard failed to bind :$dashPort within timeout"
exit 1