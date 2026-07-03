# 05-stop-all.ps1 - Kill all managed processes
# Usage:  D:\HermesData\scripts\ops\05-stop-all.ps1

param(
    [switch]$Force = $false
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping all Phoenix Sovereign services..." -ForegroundColor Yellow

# Kill llama-server
$llamaProcs = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
if ($llamaProcs) {
    Write-Host "  Killing llama-server (PID: $($llamaProcs.Id -join ', '))..." -ForegroundColor Cyan
    Stop-Process -Name "llama-server" -Force
} else {
    Write-Host "  llama-server not running." -ForegroundColor DarkGray
}

# Kill only our proxy python via WMI (not all python)
$proxyProcs = @(
    Get-CimInstance Win32_Process -Filter "Name='python.exe' AND CommandLine LIKE '%sovereign_openai_proxy%'" -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' AND CommandLine LIKE '%sovereign_openai_proxy%'" -ErrorAction SilentlyContinue
) | Where-Object { $_ }
if ($proxyProcs) {
    Write-Host "  Killing proxy python (PID: $($proxyProcs.ProcessId -join ', '))..." -ForegroundColor Cyan
    $proxyProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} else {
    Write-Host "  proxy python not running." -ForegroundColor DarkGray
}

Start-Sleep -Seconds 3
Write-Host "`nAll services stopped." -ForegroundColor Green
