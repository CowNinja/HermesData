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
        [int]$MaxAgeMinutes = 15
    )
    if (-not (Test-Path $script:AgentLog)) { return $false }
    try {
        $lines = Get-Content $script:AgentLog -Tail 400 -ErrorAction Stop
    } catch {
        return $false
    }
    $cutoff = (Get-Date).AddMinutes(-$MaxAgeMinutes)
    $pendingChat = $null
    $pendingAt = $null
    foreach ($line in $lines) {
        if ($line -match 'inbound message:.*chat=(\d+)') {
            $chat = $Matches[1]
            if ($ThreadId -and $chat -ne $ThreadId) { continue }
            if ($line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
                $pendingAt = [datetime]::Parse($Matches[1])
                if ($pendingAt -lt $cutoff) { continue }
            }
            $pendingChat = $chat
        }
        if ($pendingChat -and $line -match "response ready:.*chat=$pendingChat") {
            $pendingChat = $null
            $pendingAt = $null
        }
        if ($line -match 'Flushing text batch.*thread:([^:]+):(\d+)') {
            $tid = $Matches[2]
            if ($ThreadId -and $tid -ne $ThreadId) { continue }
            if ($line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
                $pendingAt = [datetime]::Parse($Matches[1])
                if ($pendingAt -lt $cutoff) { continue }
            }
            $pendingChat = $tid
        }
    }
    return [bool]$pendingChat
}

function Test-PhronesisMaintenanceBlocked {
    param(
        [ValidateSet('gateway_restart', 'gateway_stop', 'vram_switch', 'gateway_heal')]
        [string]$Action
    )
    $lock = Get-PhronesisMaintenanceLock
    $inFlight = Test-DiscordTurnInFlight -ThreadId ($lock.thread_id) -MaxAgeMinutes 15

    $gwPort = 8642
    $gwListening = [bool](Get-NetTCPConnection -LocalPort $gwPort -State Listen -ErrorAction SilentlyContinue)

    if ($Action -in @('gateway_restart', 'gateway_stop', 'gateway_heal')) {
        if ($inFlight -and $gwListening) {
            return @{ blocked = $true; reason = "discord_turn_in_flight" }
        }
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