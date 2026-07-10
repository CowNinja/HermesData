# Maintenance lock - blocks disruptive stack actions during Discord turns / tests.
# Usage:
#   . .\Phronesis-Maintenance-Lock.ps1
#   Set-PhronesisMaintenanceLock -Minutes 10 -Reason "OOC discord test" -ThreadId 1521146755985576116
#   Test-PhronesisMaintenanceBlocked -Action gateway_restart
param()

$script:LockFile = Join-Path (Split-Path $PSScriptRoot -Parent) "state\maintenance-lock.json"
$script:AgentLog = Join-Path (Split-Path $PSScriptRoot -Parent) "logs\agent.log"

function Get-PhronesisMaintenanceLock {
    if (-not (Test-Path $script:LockFile)) { return $null }
    try {
        $lock = Get-Content $script:LockFile -Raw | ConvertFrom-Json
        if ($lock.until) {
            $until = [datetime]::Parse($lock.until)
            if ((Get-Date) -gt $until) {
                Remove-Item $script:LockFile -Force -ErrorAction SilentlyContinue
                return $null
            }
        }
        return $lock
    } catch {
        return $null
    }
}

function Set-PhronesisMaintenanceLock {
    param(
        [int]$Minutes = 10,
        [string]$Reason = "protected window",
        [string]$ThreadId = "",
        [switch]$ProtectGateway,
        [switch]$ProtectVram,
        [switch]$Quiet
    )
    $stateDir = Split-Path $script:LockFile -Parent
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $until = (Get-Date).AddMinutes($Minutes).ToString("o")
    @{
        active          = $true
        reason          = $Reason
        until           = $until
        protect_gateway = [bool]$ProtectGateway
        protect_vram    = [bool]$ProtectVram
        thread_id       = $ThreadId
        set_at          = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -Path $script:LockFile -Encoding UTF8
    if (-not $Quiet) {
        Write-Host "Maintenance lock ON until $until ($Reason)" -ForegroundColor Cyan
    }
}

function Clear-PhronesisMaintenanceLock {
    if (Test-Path $script:LockFile) {
        Remove-Item $script:LockFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-DiscordTurnInFlight {
    param(
        [string]$ThreadId = "",
        [int]$MaxAgeMinutes = 15,
        [int]$StuckMinutes = 4
    )
    if (-not (Test-Path $script:AgentLog)) { return $false }
    try {
        $lines = Get-Content $script:AgentLog -Tail 400 -ErrorAction Stop
    } catch {
        return $false
    }
    $cutoff = (Get-Date).AddMinutes(-$MaxAgeMinutes)
    $stuckCutoff = (Get-Date).AddMinutes(-$StuckMinutes)
    $pendingChat = $null
    $pendingAt = $null
    $lastActivityAt = $null
    foreach ($line in $lines) {
        if ($line -match 'inbound message:.*chat=(\d+)') {
            $chat = $Matches[1]
            if ($ThreadId -and $chat -ne $ThreadId) { continue }
            if ($line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
                $pendingAt = [datetime]::Parse($Matches[1])
                if ($pendingAt -lt $cutoff) { continue }
            }
            $pendingChat = $chat
            $lastActivityAt = $pendingAt
        }
        if ($pendingChat -and $line -match "response ready:.*chat=$pendingChat") {
            $pendingChat = $null
            $pendingAt = $null
            $lastActivityAt = $null
        }
        if ($line -match 'Flushing text batch.*thread:([^:]+):(\d+)') {
            $tid = $Matches[2]
            if ($ThreadId -and $tid -ne $ThreadId) { continue }
            if ($line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
                $pendingAt = [datetime]::Parse($Matches[1])
                if ($pendingAt -lt $cutoff) { continue }
            }
            $pendingChat = $tid
            $lastActivityAt = $pendingAt
        }
        if ($pendingChat -and $line -match '^(?<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*(agent\.(conversation_loop|tool_executor|turn_context)|Sending response|gateway\.run: response ready)') {
            $ts = [datetime]::Parse($Matches['ts'])
            if ($ts -ge $pendingAt) { $lastActivityAt = $ts }
        }
    }
    if (-not $pendingChat) { return $false }
    # Hung API call: inbound received but no agent progress for StuckMinutes — allow heal/restart.
    if ($lastActivityAt -and $lastActivityAt -lt $stuckCutoff) { return $false }
    return $true
}

function Test-PhronesisMaintenanceBlocked {
    param(
        [ValidateSet('gateway_restart', 'gateway_stop', 'vram_switch', 'gateway_heal', 'stack_heal', 'forkguard')]
        [string]$Action
    )
    $lock = Get-PhronesisMaintenanceLock

    $gwPort = 8642
    $gwListening = [bool](Get-NetTCPConnection -LocalPort $gwPort -State Listen -ErrorAction SilentlyContinue)

    # Always defer disruptive gateway actions while a Discord turn is in-flight (no lock file required).
    if ($Action -in @('gateway_restart', 'gateway_stop', 'gateway_heal')) {
        $threadFilter = if ($lock -and $lock.thread_id) { [string]$lock.thread_id } else { "" }
        $inFlight = Test-DiscordTurnInFlight -ThreadId $threadFilter -MaxAgeMinutes 15
        if ($inFlight -and $gwListening) {
            return @{ blocked = $true; reason = "discord_turn_in_flight" }
        }
    }

    if (-not $lock) {
        return @{ blocked = $false; reason = "" }
    }

    # Hermes venv update window — block all stack respawns (Guardian/Heal/watchdog preflight).
    if ($lock.block_stack_heal -or $lock.reason -eq 'hermes_update') {
        if ($Action -in @('stack_heal', 'forkguard', 'gateway_heal', 'gateway_restart', 'gateway_stop')) {
            return @{ blocked = $true; reason = $lock.reason }
        }
    }

    if ($Action -in @('gateway_restart', 'gateway_stop', 'gateway_heal')) {
        if ($lock -and $lock.protect_gateway) {
            if ($Action -eq 'gateway_restart') {
                return @{ blocked = $true; reason = $lock.reason }
            }
            if ($Action -eq 'gateway_stop') {
                return @{ blocked = $true; reason = $lock.reason }
            }
            if ($Action -eq 'gateway_heal' -and $gwListening) {
                return @{ blocked = $true; reason = $lock.reason }
            }
        }
    }

    if ($Action -eq 'vram_switch' -and $lock -and $lock.protect_vram) {
        return @{ blocked = $true; reason = $lock.reason }
    }

    return @{ blocked = $false; reason = "" }
}