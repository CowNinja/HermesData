# Phronesis-OneButton-Stop.ps1 - Stop the full Phronesis stack.
# Usage:  powershell -File D:\HermesData\scripts\Phronesis-OneButton-Stop.ps1

$ErrorActionPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "Phronesis-ForkGuard.ps1")

Write-Host "Stopping Phronesis stack..." -ForegroundColor Yellow

Stop-Process -Name llama-server -Force -ErrorAction SilentlyContinue

@('python.exe', 'pythonw.exe') | ForEach-Object {
    Get-CimInstance Win32_Process -Filter "Name='$_'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'sovereign_openai_proxy|gateway run|hermes_cli\.main dashboard' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'server-entry\.js' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Sleep -Seconds 2
Write-Host "Stopped: llama (8090), proxy (8091), gateway (8642), dashboard (9119), workspace (3001)." -ForegroundColor Green