# Phronesis-Session.ps1 - Session-number helper for Minimal Stable Core era.
# Usage:  . .\Phronesis-Session.ps1; Get-PhronesisSession
#         . .\Phronesis-Session.ps1; Start-PhronesisSession

$script:SessionStatePath = "D:\PhronesisVault\session-state.json"

function Get-PhronesisSessionState {
    if (-not (Test-Path $script:SessionStatePath)) {
        $default = @{
            era             = "minimal-stable-core"
            activated       = "2026-07-02"
            current_session = 1
            last_event      = "Session 1 activated - stack simplified"
        }
        $default | ConvertTo-Json | Set-Content -Path $script:SessionStatePath -Encoding UTF8
    }
    return Get-Content $script:SessionStatePath -Raw | ConvertFrom-Json
}

function Get-PhronesisSession {
    return [int](Get-PhronesisSessionState).current_session
}

function Start-PhronesisSession([string]$Note = "") {
    $state = Get-PhronesisSessionState
    $state.current_session = [int]$state.current_session + 1
    $state.last_event = if ($Note) { $Note } else { "Session $($state.current_session) started" }
    $state | ConvertTo-Json | Set-Content -Path $script:SessionStatePath -Encoding UTF8
    return [int]$state.current_session
}

function Write-SessionHealthLog([string]$Summary) {
    $logPath = "D:\PhronesisVault\Session-Health-Log.md"
    $n = Get-PhronesisSession
    $line = "- **Session $n** | $(Get-Date -Format 'yyyy-MM-dd HH:mm') | $Summary"
    if (-not (Test-Path $logPath)) {
        $header = @(
            "# Phronesis Session Health Log",
            "",
            "**Era:** Minimal Stable Core (session-based tracking)",
            "**Rule:** Health is measured by Session #, not calendar day.",
            ""
        ) -join "`n"
        Set-Content -Path $logPath -Value $header -Encoding UTF8
    }
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}