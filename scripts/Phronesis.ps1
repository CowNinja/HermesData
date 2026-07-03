# Phronesis.ps1 - ONE entry point for the sovereign stack (start, heal, recover, status)
# Usage:
#   .\Phronesis.ps1 go          <- autonomous: heal + start + verify + dashboard
#   .\Phronesis.ps1 start|stop|heal|status|dashboard|smoke|recover|help

param(
    [Parameter(Position = 0)]
    [ValidateSet('go','start','stop','restart','heal','status','dashboard','smoke','recover','boot','desktop','gateway','llama','proxy','doctor','help')]
    [string]$Command = 'help',

    [Parameter(Position = 1)]
    [string]$SubCommand,

    [switch]$SkipGateway,
    [switch]$SkipDashboard,
    [switch]$SkipWorkspace,
    [switch]$SkipSmoke,
    [switch]$ForceGateway,
    [switch]$LongTest,
    [string]$Model
)

$ErrorActionPreference = "Continue"
$scriptRoot = $PSScriptRoot
$ops = Join-Path $scriptRoot "ops"

function Invoke-PhronesisScript([string]$path, [string[]]$extra = @()) {
    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $path)
    if ($extra.Count -gt 0) { $psArgs += $extra }
    & powershell @psArgs
    return $LASTEXITCODE
}

function Show-Help {
    Write-Host @"

  PHRONESIS - one-stop stack control
  =================================

  RUN THIS (99% of the time):
    go          Heal everything, start stack, smoke-test, show dashboard
    start       Start stack (auto-heals first)
    stop        Stop full stack
    heal        Fix broken ports/processes (-ForceGateway if Discord stuck)
    status      Quick port check
    dashboard   Pretty health report

  WHEN THINGS ARE REALLY BROKEN:
    recover     Admin fix: WiFi + boot tasks + full restart (elevated)
    restart     stop + start
    doctor      Fix script encoding + heal + status (run after edits)

  SETUP (once):
    boot        Register 2 Windows tasks (logon start + 5-min auto-heal)

  RARE / ADVANCED:
    smoke       Test inference chain
    desktop     Open Hermes Desktop app
    gateway     start|stop|restart|status (Discord bot on :8642)
    llama|proxy Start one layer only

  Double-click:  D:\HermesData\scripts\START-PHRONESIS.bat

"@ -ForegroundColor Cyan
}

function Invoke-Heal([switch]$Force, [switch]$Quiet) {
    $healArgs = @()
    if ($Force) { $healArgs += '-ForceGateway' }
    if ($Quiet) { $healArgs += '-Quiet' }
    $result = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "Phronesis-Heal.ps1") @healArgs
    return $(if ($result -and $result.ExitCode -ne $null) { [int]$result.ExitCode } else { 0 })
}

switch ($Command) {
    'help' {
        Show-Help
        exit 0
    }
    'go' {
        Write-Host "`n=== PHRONESIS GO (autonomous bring-up) ===" -ForegroundColor Cyan
        $code = Invoke-Heal -Force
        if ($code -ne 0) { Write-Host "Heal reported issues; continuing start..." -ForegroundColor Yellow }
        $startArgs = @()
        if ($SkipGateway)   { $startArgs += '-SkipGateway' }
        if ($SkipDashboard) { $startArgs += '-SkipDashboard' }
        if ($SkipWorkspace) { $startArgs += '-SkipWorkspace' }
        $startArgs += '-SkipSmoke'
        $code = Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-OneButton-Start.ps1") $startArgs
        if ($code -ne 0) { exit $code }
        if (-not $SkipSmoke) {
            $code = Invoke-PhronesisScript (Join-Path $ops "06-smoke-test.ps1")
            if ($code -ne 0) { Write-Host "Smoke test failed (stack may still be usable)" -ForegroundColor Yellow }
        }
        Invoke-PhronesisScript (Join-Path $ops "Phronesis-Dashboard.ps1") | Out-Null
        exit 0
    }
    'start' {
        Invoke-Heal -Quiet | Out-Null
        $args = @()
        if ($SkipGateway)   { $args += '-SkipGateway' }
        if ($SkipDashboard) { $args += '-SkipDashboard' }
        if ($SkipWorkspace) { $args += '-SkipWorkspace' }
        if ($SkipSmoke)     { $args += '-SkipSmoke' }
        exit (Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-OneButton-Start.ps1") $args)
    }
    'stop' {
        exit (Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-OneButton-Stop.ps1"))
    }
    'restart' {
        Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-OneButton-Stop.ps1") | Out-Null
        Start-Sleep -Seconds 2
        exit (Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-OneButton-Start.ps1"))
    }
    'heal' {
        exit (Invoke-Heal -Force:$ForceGateway)
    }
    'status' {
        exit (Invoke-PhronesisScript (Join-Path $ops "04-status.ps1"))
    }
    'dashboard' {
        exit (Invoke-PhronesisScript (Join-Path $ops "Phronesis-Dashboard.ps1"))
    }
    'smoke' {
        $args = @()
        if ($LongTest) { $args += '-LongTest' }
        exit (Invoke-PhronesisScript (Join-Path $ops "06-smoke-test.ps1") $args)
    }
    'recover' {
        exit (Invoke-PhronesisScript (Join-Path $ops "Phronesis-Recovery.ps1"))
    }
    'doctor' {
        Write-Host "`n=== PHRONESIS DOCTOR ===" -ForegroundColor Cyan
        Write-Host "[1/3] Normalizing script encoding to ASCII..." -ForegroundColor Gray
        $py = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
        if ($py) {
            & $py (Join-Path $scriptRoot "repair_ascii_scripts.py") --paths $scriptRoot 2>&1 | ForEach-Object { Write-Host $_ }
        } else {
            Write-Host "WARN: python not found; skipping ASCII repair" -ForegroundColor Yellow
        }
        Write-Host "[2/3] ASCII lint..." -ForegroundColor Gray
        & (Join-Path $scriptRoot "Assert-AsciiScripts.ps1") -Paths $scriptRoot
        if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: scripts still contain non-ASCII bytes" -ForegroundColor Red; exit 1 }
        Write-Host "[3/3] Stack heal + status..." -ForegroundColor Gray
        $null = . (Join-Path $scriptRoot "Phronesis-Heal.ps1") -ForceGateway -Quiet
        & (Join-Path $ops "04-status.ps1")
        exit $LASTEXITCODE
    }
    'boot' {
        exit (Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-Simplify-Boot.ps1"))
    }
    'desktop' {
        exit (Invoke-PhronesisScript (Join-Path $scriptRoot "Phronesis-Desktop-Hidden.ps1"))
    }
    'llama' {
        $args = @()
        if ($Model) { $args += '-Model'; $args += $Model }
        exit (Invoke-PhronesisScript (Join-Path $ops "02-start-llama.ps1") $args)
    }
    'proxy' {
        exit (Invoke-PhronesisScript (Join-Path $ops "03-start-proxy.ps1"))
    }
    'gateway' {
        . (Join-Path $scriptRoot "Phronesis-ForkGuard.ps1")
        $sub = if ($SubCommand) { $SubCommand.ToLower() } else { 'status' }
        $core = Get-Content (Join-Path $scriptRoot "phronesis-core.json") -Raw | ConvertFrom-Json
        $py = $core.venv_python
        $gwPort = [int]$core.ports.gateway

        switch ($sub) {
            'start' {
                Set-HermesGatewayEnv
                Start-VenvGateway
                if (Wait-GatewayReady -MaxSeconds 45) { Write-Host "Gateway UP on $gwPort" -ForegroundColor Green; exit 0 }
                Write-Host "Gateway failed to become ready" -ForegroundColor Red; exit 1
            }
            'stop' {
                Push-Location $core.hermes_root
                try {
                    $job = Start-Job { param($p) & $p -m hermes_cli.main gateway stop 2>&1 } -ArgumentList $py
                    $null = Wait-Job $job -Timeout 30
                    if ((Get-Job $job.Id).State -eq 'Running') { Stop-Job $job; Remove-Job $job -Force }
                    else { Receive-Job $job | Out-Null; Remove-Job $job -Force }
                } finally { Pop-Location }
                Start-Sleep -Seconds 2
                @(Remove-StaleGatewayZombies) | Out-Null
                Write-Host "Gateway stopped" -ForegroundColor Green
                exit 0
            }
            'restart' {
                Restart-VenvGateway
                if (Wait-GatewayReady -MaxSeconds 45) { Write-Host "Gateway restarted on $gwPort" -ForegroundColor Green; exit 0 }
                Write-Host "Gateway restart failed" -ForegroundColor Red; exit 1
            }
            'status' {
                $up = [bool](Get-NetTCPConnection -LocalPort $gwPort -State Listen -ErrorAction SilentlyContinue)
                $venv = Test-VenvOwnsGateway
                $health = Test-GatewayHealth
                Write-Host "Port ${gwPort}: $(if ($up) { 'UP' } else { 'DOWN' }) | venv=$venv | health=$health"
                exit $(if ($up -and $venv -and $health) { 0 } else { 1 })
            }
            default {
                Write-Host "Unknown gateway subcommand: $sub (use start|stop|restart|status)" -ForegroundColor Red
                exit 1
            }
        }
    }
}