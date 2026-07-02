# Phronesis unified LRU MoE router on port 8090 (replaces static 8081/8082/8083)
# Presets: python D:\PhronesisVault\scripts\model_inventory.py --reconcile
param(
    [int]$ModelsMax = 0,
    [int]$CtxSize = 0,
    [string]$PresetsPath = "D:\PhronesisVault\Operations\models-8090.ini",
    [int]$SleepIdleSeconds = -1
)

# CUDA build required for --n-gpu-layers; CPU prebuilt ignores ngl and runs full model on CPU.
$cudaPrebuilt = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-28-b9828-cuda13"
$cpuPrebuilt = "D:\PhronesisModels\binaries\test-prebuilts\2026-06-19-b9731-cpu"
$prebuiltDir = if ($env:PHRONESIS_LLAMA_BINARY_DIR) {
    $env:PHRONESIS_LLAMA_BINARY_DIR
} elseif (Test-Path (Join-Path $cudaPrebuilt "ggml-cuda.dll")) {
    $cudaPrebuilt
} else {
    $cpuPrebuilt
}
$llamaExe = Join-Path $prebuiltDir "llama-server.exe"
$logDir = "D:\PhronesisVault\Operations\logs"
$hermesScripts = "D:\HermesData\scripts"

if (-not (Test-Path $llamaExe)) {
    Write-Host "llama-server.exe not found" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $PresetsPath)) {
    Write-Host "Presets missing. Run: python D:\PhronesisVault\scripts\model_inventory.py --reconcile" -ForegroundColor Yellow
    exit 1
}

$buildLabel = if ($prebuiltDir -eq $cudaPrebuilt) { "CUDA" } else { "CPU (WARN: ngl ignored)" }
Write-Host "Binary: $buildLabel ($prebuiltDir)" -ForegroundColor Cyan
Write-Host "Enforcing unified generalist GPU preset (ngl=99)..." -ForegroundColor Cyan
$gpuPreset = python (Join-Path $hermesScripts "lru_router_manager.py") --ensure-gpu-preset 2>$null
if ($gpuPreset) { Write-Host $gpuPreset }

# Fuzzy models-max — single-pin unified generalist on 12GB VRAM
if ($ModelsMax -le 0) {
    try {
        $statusJson = python (Join-Path $hermesScripts "lru_router_manager.py") --status 2>$null
        $status = $statusJson | ConvertFrom-Json
        $ModelsMax = [int]$status.models_max_recommended
        if ($ModelsMax -le 0) { $ModelsMax = 1 }
    } catch {
        $ModelsMax = 1
    }
}

# Default ctx-size: phronesis-core.json (locked model) beats LRU VRAM heuristic
if ($CtxSize -le 0) {
    $corePath = Join-Path $hermesScripts "phronesis-core.json"
    if (Test-Path $corePath) {
        try {
            $core = Get-Content $corePath -Raw | ConvertFrom-Json
            if ($core.model_locked -and $core.ctx_size -gt 0) {
                $CtxSize = [int]$core.ctx_size
            }
        } catch { }
    }
}
if ($CtxSize -le 0) {
    try {
        $statusJson = python (Join-Path $hermesScripts "lru_router_manager.py") --status 2>$null
        $status = $statusJson | ConvertFrom-Json
        $CtxSize = [int]$status.ctx_size_recommended
        if ($CtxSize -le 0) { $CtxSize = 12288 }
    } catch {
        $CtxSize = 12288
    }
}

if ($SleepIdleSeconds -lt 0) {
    try {
        $statusJson = python (Join-Path $hermesScripts "lru_router_manager.py") --status 2>$null
        $status = $statusJson | ConvertFrom-Json
        $SleepIdleSeconds = [int]$status.sleep_idle_recommended
    } catch {
        $SleepIdleSeconds = 0
    }
}

$pids = netstat -ano | Select-String ":8090\s" | Select-String "LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -Unique
foreach ($procId in $pids) {
    if ($procId -match '^\d+$') { taskkill /F /PID $procId 2>$null | Out-Null }
}
Start-Sleep -Seconds 2

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logOut = Join-Path $logDir "llama-8090.log"
$logErr = Join-Path $logDir "llama-8090.err.log"

$parallelSlots = if ($ModelsMax -le 1) { 1 } else { 2 }
$argList = @(
    "--models-preset", $PresetsPath,
    "--host", "127.0.0.1",
    "--port", "8090",
    "--ctx-size", "$CtxSize",
    "--models-max", "$ModelsMax",
    "--parallel", "$parallelSlots",
    "--cont-batching"
)
if ($SleepIdleSeconds -gt 0) {
    $argList += @("--sleep-idle-seconds", "$SleepIdleSeconds")
}

Write-Host "Starting unified LRU router 8090 models-max=$ModelsMax sleep-idle=$SleepIdleSeconds" -ForegroundColor Cyan
Start-Process -FilePath $llamaExe -ArgumentList $argList -WorkingDirectory $prebuiltDir `
    -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr

Start-Sleep -Seconds 20
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8090/v1/models" -TimeoutSec 20
    Write-Host "8090 UP ($($resp.data.Count) logical models)" -ForegroundColor Green
    foreach ($m in $resp.data) { Write-Host ("  " + $m.id) }
    $bad = $resp.data.id | Where-Object { $_ -in @("current", "candidates") }
    if ($bad) {
        Write-Host "WARN: folder names detected - re-run reconcile + restart" -ForegroundColor Yellow
    }
    # Always-on pin: warm unified generalist into VRAM (models-max=1)
    Write-Host "Pinning resident models (unified generalist)..." -ForegroundColor Cyan
    $pinResult = python (Join-Path $hermesScripts "lru_router_manager.py") --pin-startup 2>&1
    Write-Host $pinResult
    $telJson = python (Join-Path $hermesScripts "lru_router_manager.py") --telemetry 2>$null
    if ($telJson) {
        $tel = $telJson | ConvertFrom-Json
        $resident = ($tel.pinned_resident -join ", ")
        $missing = ($tel.pinned_missing -join ", ")
        if ($tel.all_pinned_resident) {
            Write-Host "VRAM PIN OK - resident: $resident" -ForegroundColor Green
        } else {
            Write-Host "VRAM PIN PARTIAL - resident: $resident missing: $missing" -ForegroundColor Yellow
        }
    }
    # Background keepalive — re-warm pinned models if LRU evicts them
    Start-Process -FilePath "python" `
        -ArgumentList (Join-Path $hermesScripts "lru_router_manager.py"), "--keepalive" `
        -WindowStyle Hidden -WorkingDirectory $hermesScripts | Out-Null
} catch {
    Write-Host "8090 not responding. See log: $logErr" -ForegroundColor Yellow
    exit 1
}
