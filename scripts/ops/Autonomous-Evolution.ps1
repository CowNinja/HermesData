# Deep Autonomous Evolution Mode - scan, repair, log while operator AFK.
# Usage:
#   powershell -File Autonomous-Evolution.ps1 -Once
#   powershell -File Autonomous-Evolution.ps1 -DurationMinutes 60 -PollSec 30
param(
    [string]$Channel = "1521146755985576116",
    [int]$DurationMinutes = 60,
    [int]$PollSec = 30,
    [int]$SummaryIntervalMinutes = 15,
    [switch]$Once,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$root = "D:\HermesData"
$vaultOps = "D:\PhronesisVault\Operations"
$evolutionLog = Join-Path $vaultOps "Autonomous-Evolution-Log-2026-07-04.md"
$statusPath = Join-Path $vaultOps "STATUS.md"
$readinessPath = Join-Path $vaultOps "Phronesis-v0.5-Readiness-Report-2026-07-04.md"
$statePath = Join-Path $root "state\autonomous-evolution-state.json"
$py = Join-Path $root "hermes-agent\venv\Scripts\python.exe"
$started = Get-Date

function Log([string]$m) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
    if (-not $Quiet) { Write-Host $line }
    Add-Content -Path (Join-Path $root "logs\autonomous-evolution.log") -Value $line -ErrorAction SilentlyContinue
}

function New-EvoState {
    return @{
        started_at          = $started.ToString("o")
        cycles              = 0
        repairs             = @()
        last_summary_at     = $null
        improvements_ranked = @()
    }
}

function Load-State {
    if (-not (Test-Path $statePath)) { return New-EvoState }
    try {
        $raw = Get-Content $statePath -Raw | ConvertFrom-Json
        return @{
            started_at          = [string]$raw.started_at
            cycles              = [int]$raw.cycles
            repairs             = @($raw.repairs)
            last_summary_at     = $raw.last_summary_at
            improvements_ranked = @($raw.improvements_ranked)
        }
    } catch {
        return New-EvoState
    }
}

function Save-State($st) {
    New-Item -ItemType Directory -Force -Path (Split-Path $statePath) | Out-Null
    $payload = @{
        started_at          = $st.started_at
        cycles              = $st.cycles
        repairs             = @($st.repairs)
        last_summary_at     = $st.last_summary_at
        improvements_ranked = @($st.improvements_ranked)
    }
    ($payload | ConvertTo-Json -Depth 6) | Set-Content -Path $statePath -Encoding UTF8
}

function Append-EvolutionLog([string]$Section, [string]$Body) {
    New-Item -ItemType Directory -Force -Path $vaultOps | Out-Null
    if (-not (Test-Path $evolutionLog)) {
        @(
            "# Autonomous Evolution Log - 2026-07-04"
            ""
            "Deep autonomous mode for Phronesis RP / WisdomVault stack."
            ""
        ) | Set-Content -Path $evolutionLog -Encoding UTF8
    }
    Add-Content -Path $evolutionLog -Value @("", "## $Section - $(Get-Date -Format 'HH:mm:ss')", "", $Body, "") -Encoding UTF8
}

function Invoke-EvolutionCycle([hashtable]$st) {
    $actions = @()
    $healthBefore = 0
    $healthAfter = 0

    $healthJson = Join-Path $root "logs\wisdomvault-health.json"
    if (Test-Path $healthJson) {
        try {
            $h = Get-Content $healthJson -Raw | ConvertFrom-Json
            $healthBefore = [int]$h.score
        } catch {}
    }

    # Pattern: Comfy down -> start (skip when paused OR vram text / silo-primary)
    $pipelinePaused = $false
    $pauseFile = Join-Path $root "state\image-pipeline-pause.json"
    if (Test-Path $pauseFile) {
        try {
            $pauseState = Get-Content $pauseFile -Raw | ConvertFrom-Json
            $pipelinePaused = [bool]$pauseState.paused
        } catch {}
    }
    $vramMode = "unknown"
    $siloPrimary = $false
    $vramFile = Join-Path $root "state\vram-priority.json"
    if (Test-Path $vramFile) {
        try {
            $vramState = Get-Content $vramFile -Raw | ConvertFrom-Json
            $vramMode = [string]$vramState.mode
            $siloPrimary = [bool]$vramState.silo_primary
        } catch {}
    }
    $textPriority = ($vramMode -eq "text") -or $siloPrimary
    $comfyUp = $false
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 4 | Out-Null
        $comfyUp = $true
    } catch {}
    if ($pipelinePaused -or $textPriority) {
        if ($comfyUp) {
            & "D:\ComfyUI\Comfy-Stack.ps1" stop inference -Quiet 2>&1 | Out-Null
            $actions += if ($textPriority) { "stop_comfy_vram_text" } else { "stop_comfy_paused" }
        }
    } elseif (-not $comfyUp) {
        & "D:\ComfyUI\Comfy-Stack.ps1" start inference -Quiet | Out-Null
        $actions += "start_comfy_inference"
    } else {
        $mainCount = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'ComfyUI\\main\.py' }).Count
        $listenerCount = @(Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess } | Sort-Object -Unique).Count
        if ($mainCount -gt 1 -or $listenerCount -gt 1) {
            $repairOut = & "$root\scripts\ops\Repair-ComfyInference.ps1" -Quiet 2>&1
            try {
                $repairJson = ($repairOut | Where-Object { $_ -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json
                if ($repairJson.killed -and @($repairJson.killed).Count -gt 0) {
                    $actions += "repair_comfy_orphans"
                }
            } catch {}
        }
    }

    # Pattern: delivery daemon drop
    $deliveryLock = Join-Path $root "state\comfy-delivery-daemon.lock"
    $deliveryUp = $false
    if (Test-Path $deliveryLock) {
        try {
            $lockPid = [int](Get-Content $deliveryLock -Raw).Trim()
            $deliveryUp = [bool](Get-Process -Id $lockPid -ErrorAction SilentlyContinue)
        } catch {}
    }
    if (-not $deliveryUp) {
        & "$root\scripts\ops\Ensure-RP-Watchers.ps1" -Channel $Channel -Quiet | Out-Null
        $actions += "ensure_rp_watchers"
    }

    # Pattern: stale render lock
    $renderLock = Join-Path $root "state\roleplay-render.lock"
    if (Test-Path $renderLock) {
        try {
            $raw = (Get-Content $renderLock -Raw).Trim()
            $lockPid = if ($raw -match ':') { [int]($raw.Split(':')[0]) } else { [int]$raw }
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$lockPid" -ErrorAction SilentlyContinue
            if (-not $proc -or $proc.CommandLine -notmatch 'render-roleplay-image|generate\.py') {
                Remove-Item $renderLock -Force -ErrorAction SilentlyContinue
                $actions += "clear_stale_render_lock"
            }
        } catch {
            Remove-Item $renderLock -Force -ErrorAction SilentlyContinue
            $actions += "clear_bad_render_lock"
        }
    }

    # Health + simulator canaries (no Discord post)
    & "$root\scripts\ops\WisdomVault-Health.ps1" -Quiet | Out-Null
    if (Test-Path $py) {
        & $py "$root\scripts\ops\rp_simulator.py" --json-only 2>&1 | Out-Null
    }

    if (Test-Path $healthJson) {
        try {
            $h = Get-Content $healthJson -Raw | ConvertFrom-Json
            $healthAfter = [int]$h.score
        } catch {}
    }

    if ($actions.Count -gt 0) {
        $st.repairs = @($st.repairs + $actions) | Select-Object -Last 100
    }
    $st.cycles = [int]$st.cycles + 1
    Save-State $st

    return @{
        actions      = $actions
        health_before = $healthBefore
        health_after  = $healthAfter
        cycle        = $st.cycles
    }
}

function Write-StatusSnapshot([hashtable]$st, [int]$score, [string]$status) {
    $body = @(
        "# STATUS - Phronesis Stack (autonomous)"
        ""
        "**Updated:** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        "**Version:** v0.4.13 (evolution mode)"
        "**Health:** $score/100 ($status)"
        ""
        "## RP Image Pipeline"
        "- E2E: OOC -> Comfy -> gallery -> Discord MEDIA"
        "- Hybrid warm: ON (ram_prefer + ngl=38)"
        "- Delivery dedup: bootstrap + sha256 ledger"
        "- Fidelity: weighted Arabian/Levantine lane tags"
        ""
        "## Autonomous Session"
        "- Cycles: $($st.cycles)"
        "- Recent repairs: $(($st.repairs | Select-Object -Last 5) -join ', ')"
        ""
        "## Quick Commands"
        '```powershell'
        "powershell -File D:\HermesData\scripts\ops\Accelerate-Everything.ps1"
        "powershell -File D:\HermesData\scripts\ops\Magic-Heal.ps1"
        "python D:\HermesData\scripts\ops\rp_simulator.py"
        '```'
        ""
    ) -join "`n"
    [System.IO.File]::WriteAllText($statusPath, $body, (New-Object System.Text.UTF8Encoding $false))
}

function Write-ReadinessReport([hashtable]$st) {
    $health = @{ score = 0; status = "unknown" }
    $sim = @{ status = "unknown"; fidelity_parse_score = 0 }
    $hj = Join-Path $root "logs\wisdomvault-health.json"
    $sj = Join-Path $root "logs\rp-simulator-report.json"
    if (Test-Path $hj) { try { $health = Get-Content $hj -Raw | ConvertFrom-Json } catch {} }
    if (Test-Path $sj) { try { $sim = Get-Content $sj -Raw | ConvertFrom-Json } catch {} }

    $implemented = @(
        "RP loop E2E delivery (00126/00127 clean runs)",
        "Hybrid warm mode (ram_prefer)",
        "Delivery daemon dedup + bootstrap guard",
        "Repair-ComfyInference (port-aware orphan kill)",
        "Magic Heal / Accelerate Everything one-click ops",
        "RP Simulator intent canaries",
        "Ethnicity lane fidelity tags (visual_registry)",
        "Autonomous evolution loop (this session)"
    )
    $queued = @(
        "ControlNet face consistency for group shots",
        "Parallel Turbo draft backend for fast iteration",
        "Live WisdomVault dashboard LAN",
        "RAM prefetch swap daemon (dual-model hot)",
        "Second GPU or external Comfy server"
    )

    $report = @(
        "# Phronesis v0.5 Readiness Report"
        ""
        "**Generated:** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        "**Session duration:** $([math]::Round(((Get-Date) - $started).TotalMinutes, 1)) min"
        ""
        "## Health Score"
        "- WisdomVault: $($health.score)/100 ($($health.status))"
        "- RP Simulator: $($sim.status) (fidelity parse $($sim.fidelity_parse_score)%)"
        "- Evolution cycles: $($st.cycles)"
        ""
        "## Implemented (v0.4.13)"
        ($implemented | ForEach-Object { "- $_" }) -join "`n"
        ""
        "## Queued for v0.5"
        ($queued | ForEach-Object { "- $_" }) -join "`n"
        ""
        "## Recommended Next Steps (Jeff return)"
        "1. Send one OOC group test to validate ethnicity fidelity on 00128+"
        "2. Optional: enable RP Simulator cron every 6h"
        "3. Plan ControlNet / LoRA pass if ethnicity still drifts"
        "4. Consider second GPU when render queue grows"
        ""
    ) -join "`n"
    [System.IO.File]::WriteAllText($readinessPath, $report, (New-Object System.Text.UTF8Encoding $false))
}

Log "=== Autonomous Evolution start (poll=${PollSec}s duration=${DurationMinutes}m) ==="
$state = Load-State
Append-EvolutionLog "Session Start" "Autonomous evolution mode activated. Channel=$Channel"

$deadline = if ($Once) { (Get-Date).AddSeconds(1) } else { (Get-Date).AddMinutes($DurationMinutes) }
$nextSummary = (Get-Date).AddMinutes($SummaryIntervalMinutes)

while ((Get-Date) -lt $deadline) {
    $result = Invoke-EvolutionCycle $state
    if ($result.actions.Count -gt 0) {
        Log "cycle $($result.cycle): $($result.actions -join ', ') health $($result.health_before)->$($result.health_after)"
        Append-EvolutionLog "Cycle $($result.cycle)" "Repairs: $($result.actions -join ', '). Health: $($result.health_before) -> $($result.health_after)"
    } elseif (-not $Quiet -and ($result.cycle % 10 -eq 0)) {
        Log "cycle $($result.cycle): stable health=$($result.health_after)"
    }

    if ((Get-Date) -ge $nextSummary) {
        $hj = Join-Path $root "logs\wisdomvault-health.json"
        $score = 0
        $stat = "unknown"
        if (Test-Path $hj) {
            try {
                $h = Get-Content $hj -Raw | ConvertFrom-Json
                $score = [int]$h.score
                $stat = [string]$h.status
            } catch {}
        }
        Write-StatusSnapshot $state $score $stat
        Append-EvolutionLog "15m Summary" "Cycles=$($state.cycles) health=$score/$stat repairs=$($state.repairs.Count)"
        $nextSummary = (Get-Date).AddMinutes($SummaryIntervalMinutes)
        Log "summary written health=$score"
    }

    if ($result.cycle -eq 1) {
        $hj = Join-Path $root "logs\wisdomvault-health.json"
        if (Test-Path $hj) {
            try {
                $h = Get-Content $hj -Raw | ConvertFrom-Json
                Write-StatusSnapshot $state ([int]$h.score) ([string]$h.status)
            } catch {}
        }
    }

    if ($Once) { break }
    Start-Sleep -Seconds $PollSec
}

Write-ReadinessReport $state
Append-EvolutionLog "Session End" "Evolution loop complete. Cycles=$($state.cycles)"
Log "=== Autonomous Evolution complete ==="