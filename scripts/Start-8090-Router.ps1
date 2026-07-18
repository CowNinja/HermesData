# Start-8090-Router.ps1 — llama-server multi-model router (local-first three-tier)
# Research: put --models-max on CLI; clean models-8090.ini; load-on-startup DEFAULT only
param(
    [switch]$Force,
    [int]$ModelsMax = 1
)
$ErrorActionPreference = "Stop"
$exe = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13\llama-server.exe"
$ini = "D:\PhronesisVault\Operations\models-8090.ini"
$logDir = "D:\PhronesisVault\Operations\logs"
$outLog = Join-Path $logDir "llama-8090-router.out.log"
$errLog = Join-Path $logDir "llama-8090-router.err.log"

if (-not (Test-Path $exe)) { throw "llama-server missing: $exe" }
if (-not (Test-Path $ini)) { throw "preset missing: $ini" }

# Stop existing Phronesis llama on 8090
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'llama-server' -and $_.CommandLine -match '8090' } |
    ForEach-Object {
        Write-Host "Stopping PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

$argList = @(
    "--host", "127.0.0.1",
    "--port", "8090",
    "--models-preset", $ini,
    "--models-max", "$ModelsMax",
    "--models-autoload",
    "--flash-attn", "on",
    "--cache-type-k", "q8_0",
    "--cache-type-v", "q4_0"
)
Write-Host "Starting router: $exe $($argList -join ' ')"
$p = Start-Process -FilePath $exe -ArgumentList $argList -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Write-Host "PID $($p.Id) — waiting for health..."

$ready = $false
for ($i = 0; $i -lt 36; $i++) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8090/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Write-Host "  wait $($i+1)..."
}
if (-not $ready) {
    Write-Host "FAIL: 8090 not healthy. Tail err log:"
    if (Test-Path $errLog) { Get-Content $errLog -Tail 40 }
    exit 1
}
Write-Host "8090 HEALTH OK"
try {
    $m = Invoke-WebRequest "http://127.0.0.1:8090/v1/models" -UseBasicParsing -TimeoutSec 15
    Write-Host $m.Content.Substring(0, [Math]::Min(1200, $m.Content.Length))
} catch {
    Write-Host "models list: $($_.Exception.Message)"
}
exit 0
