# run-sovereign-e2e.ps1 -- Run router E2E suites with explicit exit codes (no PS pipe false fails)
param([switch]$Quiet)

$ErrorActionPreference = "Continue"
$py = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
$env:HERMES_QUIET_SECRETS = "1"

$tests = @(
    @{ Name = "moe"; Path = "D:\HermesData\scripts\test_moe_blending_e2e.py" },
    @{ Name = "t2"; Path = "D:\HermesData\scripts\test_t2_escalation_e2e.py" },
    @{ Name = "expand"; Path = "D:\HermesData\scripts\test_infinite_expand_smoke.py" }
)

$results = @{}
$idx = 0
foreach ($t in $tests) {
    if ($idx -gt 0) { Start-Sleep -Seconds 5 }
    $idx++
    if (-not $Quiet) { Write-Host "=== $($t.Name) ===" -ForegroundColor Cyan }
    & $py $t.Path
    $results[$t.Name] = $LASTEXITCODE
}

& $py D:\HermesData\scripts\cron_audit.py --summary | Out-Null
$results["cron_audit"] = $LASTEXITCODE

$fail = ($results.Values | Where-Object { $_ -ne 0 }).Count
if (-not $Quiet) {
    Write-Host ("Results: moe={0} t2={1} expand={2} cron={3}" -f `
        $results["moe"], $results["t2"], $results["expand"], $results["cron_audit"]) -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
}
exit $(if ($fail -eq 0) { 0 } else { 1 })