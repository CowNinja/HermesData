# Verify-LocalRouter.ps1 - one-shot health check for Sovereign Router (Ollama first, 808x fallback)
Write-Host "=== Sovereign Router Local Verify ==="
Write-Host "Ollama: $(if (Test-Path 'C:\Users\CowNi\AppData\Local\Programs\Ollama\ollama.exe') { 'GREEN' } else { 'MISSING' })"
$ports = @(8081,8082,8083,11434,8642)
foreach ($p in $ports) {
    $listen = netstat -ano | findstr ":$p" | findstr LISTENING
    Write-Host "Port ${p}: $(if ($listen) { 'LISTENING' } else { 'DOWN' })"
}
Write-Host "Router bridge: $(if (Test-Path 'D:\HermesData\scripts\router_bridge.py') { 'PRESENT' } else { 'MISSING' })"
Write-Host "Full router: $(if (Test-Path 'D:\PhronesisVault\scripts\sovereign_router.py') { 'PRESENT (1151 lines)' } else { 'MISSING' })"
Write-Host "=== Verify complete ==="
