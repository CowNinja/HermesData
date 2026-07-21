# Phronesis-Guardian-Body.ps1 - real 5-min heal work (must run under HERMES_HIDDEN_CHILD).
$ErrorActionPreference = "SilentlyContinue"
# Focus mode: no heal work while Jeff types / RDP
if (Test-Path "D:\HermesData\state\silo_continuous.STOP") { exit 0 }
if (Test-Path "D:\HermesData\state\silo_autonomous.STOP") { exit 0 }
if (Test-Path "D:\HermesData\state\focus_mode.STOP") { exit 0 }
$root = if ($PSScriptRoot) { $PSScriptRoot } else { "D:\HermesData\scripts" }
$hermesRoot = "D:\HermesData"
$lockPath = Join-Path $hermesRoot "state\phronesis-guardian.lock"
$py = Join-Path $hermesRoot "hermes-agent\venv\Scripts\python.exe"
$pyw = Join-Path $hermesRoot "hermes-agent\venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

function Test-PidAlive([int]$ProcessId) {
    try { $null = Get-Process -Id $ProcessId -ErrorAction Stop; return $true } catch { return $false }
}
if (Test-Path $lockPath) {
    try {
        $old = [int]((Get-Content $lockPath -Raw).Trim().Split()[0])
        if ($old -gt 0 -and (Test-PidAlive $old)) { exit 0 }
    } catch {}
}
New-Item -ItemType Directory -Force -Path (Split-Path $lockPath) | Out-Null
Set-Content -Path $lockPath -Value "$PID $(Get-Date -Format o)" -NoNewline

try {
    . (Join-Path $root "Phronesis-Maintenance-Lock.ps1")
    $block = Test-PhronesisMaintenanceBlocked -Action stack_heal
    if ($block.blocked) { exit 0 }

    $result = & (Join-Path $root "Phronesis-Heal.ps1") -Quiet

    # Belt-and-suspenders: Heal should start keepalive; ensure again here.
    try {
        . (Join-Path $root "Phronesis-ForkGuard.ps1")
        if (Get-Command Start-GatewayKeepalive -ErrorAction SilentlyContinue) {
            $null = Start-GatewayKeepalive
        }
    } catch {}

    $ensureBridge = Join-Path $hermesRoot "scripts\ops\Ensure-Grok-Direct-Bridge.ps1"
    if (Test-Path $ensureBridge) { & $ensureBridge -Quiet | Out-Null }

    if (Test-Path $pyw) {
        $inbox = Join-Path $hermesRoot "scripts\grok_inbox_consumer.py"
        $heartbeat = Join-Path $hermesRoot "scripts\grok_direct_heartbeat.py"
        $health = Join-Path $hermesRoot "scripts\phronesis_fullstack_health.py"
        . (Join-Path $root "Phronesis-ForkGuard.ps1")
        if (Test-Path $inbox) {
            $null = Invoke-HiddenProcess -FilePath $pyw -ArgumentList @($inbox, "--once") -WorkingDirectory $hermesRoot -TimeoutMs 45000
        }
        if (Test-Path $heartbeat) {
            $null = Invoke-HiddenProcess -FilePath $pyw -ArgumentList @($heartbeat, "--tick") -WorkingDirectory $hermesRoot -TimeoutMs 30000
        }
        if (Test-Path $health) {
            $null = Invoke-HiddenProcess -FilePath $pyw -ArgumentList @($health) -WorkingDirectory $hermesRoot -TimeoutMs 30000
        }
    }
    exit $(if ($result -and $null -ne $result.ExitCode) { $result.ExitCode } else { 0 })
}
finally {
    try {
        if (Test-Path $lockPath) {
            $cur = Get-Content $lockPath -Raw -ErrorAction SilentlyContinue
            if ($cur -and $cur.StartsWith("$PID")) { Remove-Item $lockPath -Force -ErrorAction SilentlyContinue }
        }
    } catch {}
}
