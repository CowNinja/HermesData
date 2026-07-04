# One-command RP image stack heal: yield VRAM, restart Comfy + gateway, start watchers.
param(
    [switch]$Quiet,
    [string]$Channel = "1521146755985576116"
)

$ErrorActionPreference = "Continue"
$root = "D:\HermesData"
$log = Join-Path $root "logs\rp-full-heal.log"

function Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    if (-not $Quiet) { Write-Host $line }
    Add-Content -Path $log -Value $line -ErrorAction SilentlyContinue
}

Log "Rp-Full-Heal start"

# Kill duplicate riders / stale generate spawns
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'roleplay-image-rider|render-roleplay-image|generate\.py' } |
    ForEach-Object {
        Log "stop pid=$($_.ProcessId) $($_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length)))"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Clear stale render lock
$lock = Join-Path $root "state\roleplay-render.lock"
if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue; Log "cleared render lock" }

# Yield llama VRAM for image stack
& "$root\scripts\Phronesis-Yield-VRAM-For-Image.ps1" -Quiet
Start-Sleep -Seconds 3

# Restart Comfy inference (hidden pythonw)
& "D:\ComfyUI\Comfy-Stack.ps1" restart inference -Quiet
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8188/system_stats" -UseBasicParsing -TimeoutSec 4
        if ($r.StatusCode -eq 200) { Log "ComfyUI ready :8188"; break }
    } catch {}
    Start-Sleep -Seconds 4
}

# Gateway hard restart
& "$root\scripts\Phronesis.ps1" gateway restart
Start-Sleep -Seconds 5

# Singleton delivery + rider daemons (no duplicate spawns)
& "$root\scripts\ops\Ensure-RP-Watchers.ps1" -Channel $Channel -Quiet:$Quiet
Log "RP watchers ensured channel=$Channel"

Log "Rp-Full-Heal complete"
if (-not $Quiet) {
    Write-Host "Heal complete. Resend OOC in thread $Channel after /reset"
}