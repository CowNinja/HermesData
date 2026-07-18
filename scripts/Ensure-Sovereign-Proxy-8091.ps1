# Ensure-Sovereign-Proxy-8091.ps1 — keep MoE gateway up (venv only, logged)
# Use when 8091 flaps or after heal/restart thrash.
# Uses Start-HiddenProcess (CreateNoWindow) — NEVER Start-Process -Redirect* which
# allocates a console and steals focus while Jeff is typing.
$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
$pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$script = "D:\HermesData\scripts\sovereign_openai_proxy.py"
$logDir = "D:\PhronesisVault\Operations\logs"
$out = Join-Path $logDir "proxy-8091.out.log"
$err = Join-Path $logDir "proxy-8091.err.log"
$launcher = if (Test-Path $pyw) { $pyw } else { $py }

. (Join-Path $scriptDir "Phronesis-ForkGuard.ps1")

function Test-8091 {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8091/health" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

if (Test-8091) {
    Write-Host "8091 already healthy"
    exit 0
}

# Prefer registered task (survives Job Objects / shell exits; no focus steal)
$task = Get-ScheduledTask -TaskName "Hermes_Proxy_8091" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Starting proxy via scheduled task Hermes_Proxy_8091..."
    Start-ScheduledTask -TaskName "Hermes_Proxy_8091"
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        if (Test-8091) { Write-Host "8091 GREEN after $($i+1)s (task)"; exit 0 }
    }
}

# Stop any proxy on 8091
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'sovereign_openai_proxy' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

if (-not (Test-Path $launcher)) { Write-Host "FATAL: missing $launcher"; exit 1 }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
"$(Get-Date -Format o) Ensure-Sovereign-Proxy starting launcher=$launcher" | Out-File -Append -FilePath $out
Write-Host "Starting proxy via Start-HiddenProcess (pythonw, no console)..."

$startScript = Join-Path $scriptDir "Start-Sovereign-Proxy-8091.ps1"
if (Test-Path $startScript) {
    & $startScript
    if (Test-8091) { exit 0 }
}

$null = Start-HiddenProcess -FilePath $launcher `
    -ArgumentList @($script, "--host", "127.0.0.1", "--port", "8091") `
    -WorkingDirectory "D:\HermesData\scripts"

for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Test-8091) {
        Write-Host "8091 GREEN after $($i+1)s"
        exit 0
    }
}
Write-Host "FAIL: 8091 not healthy"
if (Test-Path $err) { Get-Content $err -Tail 20 }
exit 1
