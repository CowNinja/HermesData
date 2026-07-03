# Phronesis-Desktop-Hidden.ps1 - Launch Hermes Desktop with hidden child processes (Session 5).
# Suppresses console flashes from pythonw/node backend spawns.

$ErrorActionPreference = "SilentlyContinue"
$env:HERMES_CHILD_PROCESS_HIDDEN = "1"
$env:HERMES_DESKTOP_QUIET_PLUGIN_LOAD = "1"
$env:HERMES_GATEWAY_RESPONSE_TRUNCATION_GUARD = "1"
$env:HERMES_GATEWAY_FORCE_FINISH_REASON = "1"

$repoRoot = if ($env:HERMES_DATA) { $env:HERMES_DATA } else { "D:\HermesData" }
$desktopCandidates = @(
    "$repoRoot\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe",
    "$repoRoot\hermes-agent\apps\desktop\dist\win-unpacked\Hermes.exe",
    "$env:LOCALAPPDATA\Programs\Hermes\Hermes.exe",
    "$env:LOCALAPPDATA\hermes\Hermes.exe"
)

$exe = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $exe) {
    Write-Host "Hermes Desktop not found. Open from Start Menu after install." -ForegroundColor Yellow
    exit 1
}

Start-Process -FilePath $exe -WindowStyle Normal
Write-Host "Hermes Desktop started (hidden child processes enabled)." -ForegroundColor Green