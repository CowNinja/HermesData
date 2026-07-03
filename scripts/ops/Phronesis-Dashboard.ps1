# Phronesis-Dashboard.ps1 - Session-aware stack health (phronesis-core.json)
. (Join-Path (Split-Path $PSScriptRoot -Parent) "Phronesis-Session.ps1")
. (Join-Path (Split-Path $PSScriptRoot -Parent) "Phronesis-ForkGuard.ps1")

$corePath = Join-Path (Split-Path $PSScriptRoot -Parent) "phronesis-core.json"
$core = Get-Content $corePath -Raw | ConvertFrom-Json
$session = Get-PhronesisSession

Write-Host @"

  ==========================================
   PHRONESIS DASHBOARD v2.0 (Session #$session)
   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  ==========================================
"@ -ForegroundColor Cyan

function Port-Up([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

$ports = @(
    @{ Port = [int]$core.ports.router;    Label = "llama" },
    @{ Port = [int]$core.ports.proxy;     Label = "proxy" },
    @{ Port = [int]$core.ports.gateway;   Label = "gateway" },
    @{ Port = [int]$core.ports.dashboard; Label = "dashboard" },
    @{ Port = [int]$core.ports.workspace; Label = "workspace" }
)

$up = 0
foreach ($p in $ports) {
    $listening = Port-Up $p.Port
    if ($listening) { $up++ }
    $c = if ($listening) { "Green" } else { "Red" }
    Write-Host "  [$c]  Port $($p.Port) ($($p.Label)): $(if ($listening) { 'UP' } else { 'DOWN' })" -ForegroundColor $c
}

$venvProxy = Test-VenvOwns8091
$venvGw = Test-VenvOwnsGateway
$venvDash = Test-VenvOwnsDashboard
$llama = @(Get-Process llama-server -ErrorAction SilentlyContinue).Count
$healthy = ($up -ge 2) -and ($llama -le 1) -and $venvProxy -and $venvGw
$status = if ($healthy) { "healthy" } else { "DEGRADED" }

Write-Host ""
Write-Host "  Session #$session $status | $up/$($ports.Count) ports | $llama llama | venv proxy=$venvProxy gw=$venvGw dash=$venvDash" -ForegroundColor $(if ($healthy) { "Green" } else { "Yellow" })

Write-Host ""
foreach ($t in @("Phronesis-Start-At-Logon", "Phronesis-Guardian")) {
    $s = (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue).State
    $c = if ($s -eq 'Ready') { 'Green' } else { 'Red' }
    Write-Host "  [$c]  Task ${t}: $s" -ForegroundColor $c
}

$gpu = nvidia-smi --query-gpu=memory.free,memory.used,temperature.gpu --format=csv,noheader,nounits 2>$null
if ($gpu) {
    $parts = $gpu -split ', '
    $free = [int]$parts[0]
    $c = if ($free -gt 3000) { 'Green' } elseif ($free -gt 1000) { 'Yellow' } else { 'Red' }
    Write-Host "  [$c]  VRAM: $free MB free / $($parts[1]) MB used @ $($parts[2])C" -ForegroundColor $c
}

try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($core.ports.router)/v1/models" -UseBasicParsing -TimeoutSec 2
    $model = ($resp.Content | ConvertFrom-Json).data[0].id
    Write-Host "  [INFO] Model: $(Split-Path $model -Leaf)" -ForegroundColor Cyan
} catch {
    Write-Host "  [WARN] Model: no response from llama-server" -ForegroundColor Yellow
}

try {
    $gw = Invoke-RestMethod -Uri "http://127.0.0.1:$($core.ports.gateway)/health" -TimeoutSec 2
    Write-Host "  [GREEN] Gateway: $($gw.status) v$($gw.version)" -ForegroundColor Green
} catch {
    Write-Host "  [YELLOW] Gateway: not responding" -ForegroundColor Yellow
}

Write-Host ""