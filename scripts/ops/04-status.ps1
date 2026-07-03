# 04-status.ps1 - Health-check sovereign stack (phronesis-core.json)
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path $PSScriptRoot -Parent
$core = Get-Content (Join-Path $root "phronesis-core.json") -Raw | ConvertFrom-Json
. (Join-Path $root "Phronesis-ForkGuard.ps1")

$services = @(
    @{ Name = "LLAMA";    Port = [int]$core.ports.router;   Path = "/v1/models" },
    @{ Name = "PROXY";    Port = [int]$core.ports.proxy;   Path = "/health" },
    @{ Name = "GATEWAY";  Port = [int]$core.ports.gateway; Path = "/health" },
    @{ Name = "DASH";     Port = [int]$core.ports.dashboard; Path = "/health" }
)

$ok = 0
foreach ($svc in $services) {
    $url = "http://127.0.0.1:$($svc.Port)$($svc.Path)"
    try {
        $r = Invoke-RestMethod -Uri $url -TimeoutSec 5 -ErrorAction Stop
        $detail = ""
        if ($svc.Name -eq "LLAMA" -and $r.data -and $r.data[0].id) {
            $detail = " -> $(Split-Path $r.data[0].id -Leaf)"
        }
        Write-Host "[$($svc.Port)] $($svc.Name) -> OK$detail" -ForegroundColor Green
        $ok++
    } catch {
        Write-Host "[$($svc.Port)] $($svc.Name) -> DOWN" -ForegroundColor Red
    }
}

$venvProxy = Test-VenvOwns8091
$venvGw = Test-VenvOwnsGateway
$venvDash = Test-VenvOwnsDashboard
Write-Host "venv: proxy=$venvProxy gateway=$venvGw dashboard=$venvDash" -ForegroundColor $(if ($venvProxy -and $venvGw -and $venvDash) { "Green" } else { "Yellow" })
Write-Host "`n[DONE] $ok/$($services.Count) ports healthy" -ForegroundColor $(if ($ok -eq $services.Count) { "Green" } else { "Yellow" })