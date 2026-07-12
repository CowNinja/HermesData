# BW leftovers — re-unlock + re-analyze + apply remaining dupes only
# Run in the open PowerShell window (non-elevated):
#   $env:BW_EMAIL='mr.jeffrey.j.bloom@gmail.com'
#   $env:BW_PASSWORD='***'   # type it; do not save
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_leftovers.ps1"
#   Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue

$ErrorActionPreference = "Continue"
$Bw = "D:\HermesData\bin\bw.cmd"
$Work = "D:\HermesData\state\secrets-work"
$Py = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

if (-not $env:BW_EMAIL) { $env:BW_EMAIL = "mr.jeffrey.j.bloom@gmail.com" }
if (-not $env:BW_PASSWORD) {
  Write-Host "Set BW_PASSWORD env then re-run. No password baked in."
  exit 2
}

Write-Host "=== BW leftovers ==="
& $Bw logout 2>$null | Out-Null
$login = & $Bw login $env:BW_EMAIL $env:BW_PASSWORD --raw 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "login failed: $login"
  exit 1
}
$session = & $Bw unlock $env:BW_PASSWORD --raw 2>&1
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($session)) {
  Write-Host "unlock failed: $session"
  exit 1
}
$session = ($session | Select-Object -Last 1).ToString().Trim()
$env:BW_SESSION = $session
$session | Set-Content -Path (Join-Path $Work "bw-session.txt") -Encoding ascii
Write-Host "unlocked"

& $Bw sync 2>&1 | Out-Host
& $Bw list items 2>&1 | Set-Content -Path (Join-Path $Work "bw-items-raw-leftovers.json") -Encoding utf8
Write-Host "list done"

# analyze to safe plan (no passwords in outputs)
& $Py "D:\HermesData\scripts\bw_analyze_from_raw.py" --raw (Join-Path $Work "bw-items-raw-leftovers.json") 2>&1 | Out-Host

# apply remaining (script uses plan files in secrets-work)
& $Py "D:\HermesData\scripts\bw_dedupe_apply.py" --apply 2>&1 | Out-Host

& $Bw lock 2>&1 | Out-Host
Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:BW_SESSION -ErrorAction SilentlyContinue
Write-Host "=== leftovers done; vault locked ==="
