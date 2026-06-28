#Requires -Version 5.1
param(
    [switch]$SkipServerStart,
    [switch]$TryStartServers
)

$ErrorActionPreference = "Continue"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = "D:\PhronesisVault\Operations\logs\local-verification"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "local-verification-$ts.log"

function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    switch ($Level) {
        "PASS" { Write-Host $line -ForegroundColor Green }
        "FAIL" { Write-Host $line -ForegroundColor Red }
        "WARN" { Write-Host $line -ForegroundColor Yellow }
        default { Write-Host $line }
    }
}

function Test-PortOpen([int]$Port) {
    try {
        $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
        return [bool]$r.TcpTestSucceeded
    } catch {
        return $false
    }
}

function Invoke-CmdLog {
    param(
        [string]$Label,
        [string]$Command
    )
    Write-Log ("--- " + $Label + " ---")
    Write-Log ("CMD: " + $Command)
    try {
        $out = Invoke-Expression $Command 2>&1 | Out-String
        if ($out.Trim()) {
            Add-Content -Path $logFile -Value $out -Encoding UTF8
        }
        return $out
    } catch {
        Write-Log ("Exception: " + $_.Exception.Message) "FAIL"
        return ""
    }
}

Write-Log "Phronesis Local Verification started"
Write-Log ("Log file: " + $logFile)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Log ("User: " + $env:USERNAME + " | Elevated: " + $isAdmin)

if (Test-Path "D:\PhronesisVault") {
    Write-Log "VAULT_CONFIRMED=D:\PhronesisVault" "PASS"
} else {
    Write-Log "PhronesisVault missing" "FAIL"
}

Write-Log "=== PORT MATRIX ==="
$ports = @(11434, 8081, 8082, 8083, 8090)
$portState = @{}
foreach ($p in $ports) {
    $up = Test-PortOpen $p
    $portState[$p] = $up
    if ($up) {
        Write-Log ("Port " + $p + " UP") "PASS"
    } else {
        Write-Log ("Port " + $p + " DOWN") "WARN"
    }
}

if ($TryStartServers -and -not $SkipServerStart) {
    Write-Log "=== ATTEMPT Start-SovereignServers ==="
    $startScript = "D:\PhronesisVault\tests\Start-SovereignServers.ps1"
    if (Test-Path $startScript) {
        & $startScript -Daily -Classifier 2>&1 | ForEach-Object { Write-Log $_.ToString() }
        Start-Sleep -Seconds 8
        foreach ($p in @(8081, 8082, 8083)) {
            $up = Test-PortOpen $p
            if ($up) { Write-Log ("Post-start port " + $p + " UP") "PASS" }
            else { Write-Log ("Post-start port " + $p + " DOWN") "WARN" }
        }
    } else {
        Write-Log "Start-SovereignServers.ps1 not found" "FAIL"
    }
}

Invoke-CmdLog "Ollama list" "ollama list"
Invoke-CmdLog "HermesData sovereign_router" "python D:\HermesData\scripts\sovereign_router.py"
Invoke-CmdLog "Router bridge" "python D:\HermesData\scripts\router_bridge.py"

$llamaPortsUp = $portState[8081] -or $portState[8082] -or $portState[8083]
if ($llamaPortsUp) {
    Push-Location "D:\PhronesisVault\scripts"
    Invoke-CmdLog "Vault tier tests" "python test_sovereign_router_tiers.py -q"
    Pop-Location
} else {
    Write-Log "Skipping tier tests - llama ports down" "WARN"
}

$auditOut = Invoke-CmdLog "Model inventory audit" "python D:\PhronesisVault\scripts\model_inventory.py --audit"
if ($auditOut -match '"drift_count":\s*(\d+)') {
    $drift = [int]$Matches[1]
    if ($drift -eq 0) {
        Write-Log ("gguf_drift_count=" + $drift + " OK") "PASS"
    } elseif ($drift -le 5) {
        Write-Log ("gguf_drift_count=" + $drift + " low") "WARN"
    } else {
        Write-Log ("gguf_drift_count=" + $drift + " run: python model_inventory.py --reconcile") "WARN"
    }
}

# 8090 is optional when MoE 808x stack is up
$moeUp = $portState[8081] -and $portState[8083]
if (-not $portState[8090] -and $moeUp) {
    Write-Log "Port 8090 DOWN but optional (MoE 808x production path active)" "PASS"
} elseif ($portState[8090]) {
    Write-Log "Port 8090 UP (unified router mode)" "PASS"
} else {
    Write-Log "Port 8090 DOWN and MoE incomplete" "WARN"
}

$tokenLog = "D:\PhronesisVault\Operations\token-usage-local.jsonl"
if (Test-Path $tokenLog) {
    Write-Log "token-usage-local.jsonl exists" "PASS"
    Get-Content $tokenLog -Tail 5 | ForEach-Object { Write-Log ("  " + $_) }
} else {
    Write-Log "token-usage-local.jsonl not created yet" "WARN"
}

$provDir = "D:\PhronesisVault\Operations\provenance-cache"
if (Test-Path $provDir) {
    $recent = Get-ChildItem $provDir -Filter "*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
    Write-Log ("Recent provenance trails: " + $recent.Count) "PASS"
    foreach ($f in $recent) {
        Write-Log ("  " + $f.Name)
    }
}

Write-Log "=== SUMMARY ==="
$ollamaOk = $portState[11434]
$llamaOk = $portState[8081] -or $portState[8082] -or $portState[8083] -or $portState[8090]
if ($ollamaOk -and $llamaOk) {
    Write-Log "STATUS GREEN - both Ollama and llama tiers up" "PASS"
} elseif ($ollamaOk) {
    Write-Log "STATUS YELLOW - Ollama only interim mode" "WARN"
} else {
    Write-Log "STATUS RED - no local backend" "FAIL"
}

Write-Log "Verification complete"
Write-Log $logFile "PASS"
Write-Host ""
Write-Host ("Log written to: " + $logFile) -ForegroundColor Cyan
