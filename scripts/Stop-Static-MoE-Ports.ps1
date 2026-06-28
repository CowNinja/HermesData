# Stop legacy static llama-server listeners on 8081/8082/8083 (P2 cutover prep)
param(
    [int[]]$Ports = @(8081, 8082, 8083)
)

Write-Host "=== Stop Static MoE Ports ===" -ForegroundColor Cyan
foreach ($port in $Ports) {
    $pids = netstat -ano | Select-String ":$port\s" | Select-String "LISTENING" | ForEach-Object {
        ($_ -split '\s+')[-1]
    } | Select-Object -Unique
    if (-not $pids) {
        Write-Host "Port $port : already free" -ForegroundColor DarkGray
        continue
    }
    foreach ($procId in $pids) {
        if ($procId -match '^\d+$') {
            Write-Host "Stopping PID $procId on port $port" -ForegroundColor Yellow
            taskkill /F /PID $procId 2>$null | Out-Null
        }
    }
}
Start-Sleep -Seconds 2
foreach ($port in $Ports) {
    $still = netstat -ano | Select-String ":$port\s" | Select-String "LISTENING"
    if ($still) {
        Write-Host "Port $port : STILL LISTENING" -ForegroundColor Red
    } else {
        Write-Host "Port $port : free" -ForegroundColor Green
    }
}
