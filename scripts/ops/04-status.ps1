# 04-status.ps1 — Health-check all managed services
# Usage:  D:\HermesData\scripts\ops\04-status.ps1

$ErrorActionPreference = "SilentlyContinue"
$services = @(
    @{ Name = "PROXY";   Port = 8091; Path = "/health" },
    @{ Name = "LLAMA";   Port = 8090; Path = "/v1/models" }
)

$ok = 0
$total = $services.Count

foreach ($svc in $services) {
    $url = "http://127.0.0.1:$($svc.Port)$($svc.Path)"
    try {
        $r = Invoke-RestMethod -Uri $url -TimeoutSec 5 -ErrorAction Stop
        $status = "OK"
        $ok++
        $detail = ""
        if ($svc.Port -eq 8091) {
            # Try to extract backend info from proxy health
            $detail = ""
        }
        if ($r.data -and $r.data.Count -gt 0 -and $r.data[0].id) { $detail = " -> $($r.data[0].id)" }
        Write-Host "[$($svc.Port)] $($svc.Name) -> $status$detail" -ForegroundColor Green
    } catch {
        Write-Host "[$($svc.Port)] $($svc.Name) -> DOWN" -ForegroundColor Red
    }
}

Write-Host "`n[DONE] $ok/$total services healthy" -ForegroundColor $(if ($ok -eq $total) { "Green" } else { "Yellow" })
