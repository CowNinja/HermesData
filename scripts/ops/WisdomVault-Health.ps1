# WisdomVault stack health - human summary + JSON report for dashboards/cron.
param(
    [switch]$JsonOnly,
    [switch]$Quiet
)

$root = "D:\HermesData"
$reportPath = Join-Path $root "logs\wisdomvault-health.json"

function Port-Up([int]$port) {
    $tcp = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($tcp.Count -gt 0) { return $true }
    $hits = netstat -ano 2>$null | Select-String ":$port\s" | Select-String 'LISTENING'
    return [bool]$hits
}

function Service-Up([int]$port, [string]$healthUrl) {
    if (Port-Up $port) { return $true }
    if (-not $healthUrl) { return $false }
    try {
        Invoke-RestMethod -Uri $healthUrl -TimeoutSec 4 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Daemon-Up([string]$lockPath) {
    if (-not (Test-Path $lockPath)) { return $false }
    try {
        $lockPid = [int](Get-Content $lockPath -Raw).Trim()
        return [bool](Get-Process -Id $lockPid -ErrorAction SilentlyContinue)
    } catch { return $false }
}

$checks = @{}
$score = 0
foreach ($entry in @(
    @{ Key = "llama_8090"; Port = 8090; W = 12; Url = "http://127.0.0.1:8090/v1/models" },
    @{ Key = "gateway_8642"; Port = 8642; W = 12; Url = "http://127.0.0.1:8642/health" },
    @{ Key = "comfy_8188"; Port = 8188; W = 12; Url = "http://127.0.0.1:8188/system_stats" },
    @{ Key = "gallery_8189"; Port = 8189; W = 12; Url = "http://127.0.0.1:8189/" }
)) {
    $up = Service-Up $entry.Port $entry.Url
    $checks[$entry.Key] = $up
    if ($up) { $score += $entry.W }
}

$hybridPath = Join-Path $root "state\hybrid-vram-profile.json"
$checks.hybrid_active = $false
if (Test-Path $hybridPath) {
    try {
        $prof = Get-Content $hybridPath -Raw | ConvertFrom-Json
        $checks.hybrid_active = [bool]$prof.active
        if ($prof.active) { $score += 8 }
    } catch {}
}

$deliveryLock = Join-Path $root "state\comfy-delivery-daemon.lock"
$checks.delivery_daemon = Daemon-Up $deliveryLock
if ($checks.delivery_daemon) { $score += 10 }

$renderLock = Join-Path $root "state\roleplay-render.lock"
$checks.render_lock = $false
if (Test-Path $renderLock) {
    try {
        $raw = (Get-Content $renderLock -Raw).Trim()
        $lockPid = if ($raw -match ':') { [int]($raw.Split(':')[0]) } else { [int]$raw }
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$lockPid" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -match 'render-roleplay-image|generate\.py') {
            $checks.render_lock = $true
        }
    } catch {
        $checks.render_lock = $true
    }
}
if (-not $checks.render_lock) { $score += 6 }

$comfyMainCount = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ComfyUI\\main\.py' }).Count
$comfyListenerCount = @(Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { $_.OwningProcess } | Sort-Object -Unique).Count
$checks.comfy_main_py_count = $comfyMainCount
$checks.comfy_listener_count = $comfyListenerCount
$checks.comfy_orphan_main = ($comfyMainCount -gt $comfyListenerCount)
$checks.comfy_duplicate_listener = ($comfyListenerCount -gt 1)
$checks.comfy_duplicate_main = $checks.comfy_orphan_main -or $checks.comfy_duplicate_listener
if (-not $checks.comfy_duplicate_main) { $score += 6 }

$latestOut = Get-ChildItem "D:\ComfyUI\output\standard__*.png" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$latestGal = Get-ChildItem "D:\ComfyUI\gallery\images\*.png" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

$vramFree = 0
$gpu = nvidia-smi --query-gpu=memory.free,memory.used --format=csv,noheader,nounits 2>$null
if ($gpu) {
    $parts = $gpu -split ', '
    $vramFree = [int]$parts[0]
    $checks.vram_free_mb = $vramFree
    $checks.vram_used_mb = [int]$parts[1]
    if ($vramFree -gt 2000) { $score += 8 }
}

$score = [Math]::Min(100, $score)
$status = if ($score -ge 85) { "healthy" } elseif ($score -ge 65) { "degraded" } else { "critical" }

$report = [ordered]@{
    timestamp       = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    version         = "v0.4.13"
    status          = $status
    score           = $score
    checks          = $checks
    latest_output   = if ($latestOut) { $latestOut.Name } else { $null }
    latest_gallery  = if ($latestGal) { $latestGal.Name } else { $null }
    recommendations = @(
        @(
            if (-not $checks.delivery_daemon) { "Run Ensure-RP-Watchers.ps1 - delivery daemon not running" }
            if ($checks.comfy_orphan_main) { "Run Repair-ComfyInference.ps1 - orphan main.py not on :8188" }
            if ($checks.comfy_duplicate_listener) { "Run Repair-ComfyInference.ps1 - duplicate :8188 listeners" }
            if ($checks.render_lock) { "Clear stale roleplay-render.lock if no render active" }
            if (-not $checks.hybrid_active) { "Enable hybrid warm: Phronesis-Hybrid-Warm-Mode.ps1 -Mode On" }
            if (-not $checks.comfy_8188) { "Start Comfy: D:\ComfyUI\Comfy-Stack.ps1 start inference" }
            if (-not $checks.llama_8090) { "Start llama: Phronesis-Hybrid-Warm-Mode.ps1 -Mode On" }
            "Community: keep RAM prefetch + novram/ram_prefer; use draft previews for fidelity iteration"
        ) | Where-Object { $_ }
    )
}

$json = $report | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($reportPath, $json, (New-Object System.Text.UTF8Encoding $false))

if (-not $JsonOnly -and -not $Quiet) {
    Write-Host "WisdomVault Health: $status ($score/100)"
    Write-Host "  output: $($report.latest_output) | gallery: $($report.latest_gallery)"
    Write-Host "  delivery_daemon=$($checks.delivery_daemon) hybrid=$($checks.hybrid_active) vram_free=${vramFree}MB"
    Write-Host "Report: $reportPath"
}

if ($JsonOnly) { $report | ConvertTo-Json -Depth 5 }