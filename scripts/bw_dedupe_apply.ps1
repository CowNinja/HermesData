# ==============================================================================
# Bitwarden DE-DUPE APPLY (ASCII only)
# Policy (Jeff green light):
#   - Keep NEWEST item per (host + username)
#   - Merge all URIs + keep best password/TOTP into that one entry
#   - Delete the rest
# NO passwords written to log files.
#
# DRY-RUN (safe, default):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_dedupe_apply.ps1"
#
# APPLY (actually merge + delete):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_dedupe_apply.ps1" -Apply
#
# Remote password:
#   $env:BW_EMAIL = 'mr.jeffrey.j.bloom@gmail.com'
#   $env:BW_PASSWORD = 'your-master-password'
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_dedupe_apply.ps1" -Apply
#   Remove-Item Env:BW_PASSWORD
# ==============================================================================

param(
    [string]$Password = "",
    [string]$Email = "mr.jeffrey.j.bloom@gmail.com",
    [switch]$Apply,
    [switch]$SkipRelogin
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$BwCmd = "D:\HermesData\bin\bw.cmd"
if (-not (Test-Path -LiteralPath $BwCmd)) {
    $alt = Join-Path $env:APPDATA "npm\bw.cmd"
    if (Test-Path -LiteralPath $alt) { $BwCmd = $alt }
}

$Python = "python"
$ApplyPy = "D:\HermesData\scripts\bw_dedupe_apply.py"
$OutDir = "D:\HermesData\state\secrets-work"
$LogPath = Join-Path $OutDir "bw-dedupe-apply-wrapper-log.txt"
$SessionPath = Join-Path $OutDir "bw-session.txt"

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding Ascii -ErrorAction SilentlyContinue } catch {}
    Write-Host $line
}

try { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null } catch {}
Set-Content -LiteralPath $LogPath -Value "bw dedupe apply wrapper" -Encoding Ascii
Write-Log "start"
Write-Log ("apply_switch=" + [bool]$Apply)

if (-not (Test-Path -LiteralPath $BwCmd)) { Write-Host "ERROR no bw"; exit 1 }
if (-not (Test-Path -LiteralPath $ApplyPy)) { Write-Host "ERROR no python apply script"; exit 1 }

# password
$plain = ""
if (-not [string]::IsNullOrWhiteSpace($Password)) { $plain = $Password.Trim(); Write-Log "password_source=param" }
elseif (-not [string]::IsNullOrWhiteSpace($env:BW_PASSWORD)) { $plain = $env:BW_PASSWORD.Trim(); Write-Log "password_source=env" }
else {
    Write-Host "Enter Bitwarden MASTER PASSWORD (hidden)..."
    try {
        $secure = Read-Host -AsSecureString "Master password"
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
        finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null }
        Write-Log "password_source=read_host"
    } catch {
        Write-Log ("read_host_error=" + $_.Exception.Message)
    }
}

if ([string]::IsNullOrWhiteSpace($plain)) {
    Write-Host "ERROR no password"
    Write-Host '  $env:BW_PASSWORD = ''your-password'''
    Write-Host '  then re-run'
    exit 1
}
Write-Log ("password_len=" + $plain.Length)

if (-not [string]::IsNullOrWhiteSpace($env:BW_EMAIL)) { $Email = $env:BW_EMAIL }

if (-not $SkipRelogin) {
    Write-Host "Logout/Login refresh..."
    try { & $BwCmd logout 2>&1 | Out-Null } catch {}
    $env:BW_PASSWORD = $plain
    $loginOut = & $BwCmd login $Email --passwordenv BW_PASSWORD 2>&1 | Out-String
    Write-Log ("login=" + $loginOut.Trim().Substring(0, [Math]::Min(200, $loginOut.Trim().Length)))
    if ($loginOut -match "Invalid master password|incorrect|Cryptography error") {
        Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue
        Write-Host "LOGIN FAILED"
        exit 2
    }
}

Write-Host "Unlock..."
$env:BW_PASSWORD = $plain
$unlockOut = & $BwCmd unlock --passwordenv BW_PASSWORD --raw 2>&1
Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue
$plain = $null
$Password = $null

$session = ""
if ($unlockOut -is [System.Array]) {
    $session = ($unlockOut | ForEach-Object { "$_" }) -join "`n"
} else {
    $session = [string]$unlockOut
}
$session = $session.Trim()
$parts = @($session -split "(`r`n|`n)" | Where-Object { $_.Trim().Length -gt 0 })
if ($parts.Count -gt 0) { $session = $parts[-1].Trim() }

if ($session.Length -lt 20 -or $session -match "Cryptography|Invalid|Error") {
    Write-Log ("unlock_failed=" + $session)
    Write-Host "UNLOCK FAILED"
    exit 2
}
Write-Log ("session_len=" + $session.Length)
Set-Content -LiteralPath $SessionPath -Value $session -Encoding Ascii -NoNewline
$env:BW_SESSION = $session

$st = & $BwCmd status 2>&1 | Out-String
Write-Log ("status=" + $st.Trim())
if ($st -notmatch '"status"\s*:\s*"unlocked"') {
    Write-Host "Not unlocked"
    exit 3
}

Write-Host "Sync..."
& $BwCmd sync 2>&1 | Out-Null

if ($Apply) {
    Write-Host "APPLY mode: merge URIs into newest, delete duplicates..."
    $pyArgs = @($ApplyPy, "--apply")
} else {
    Write-Host "DRY-RUN mode: plan only (no vault changes)..."
    $pyArgs = @($ApplyPy)
}

$pyOut = & $Python @pyArgs 2>&1 | Out-String
Write-Log ("python_done len=" + $pyOut.Length)
Write-Host $pyOut

# optional lock
try { & $BwCmd lock 2>&1 | Out-Null } catch {}
Remove-Item Env:BW_SESSION -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "============================================================"
if ($Apply) {
    Write-Host " APPLY finished. Tell Hermes: bw dedupe apply done"
} else {
    Write-Host " DRY-RUN finished. Review summary, then re-run with -Apply"
    Write-Host " Tell Hermes: bw dedupe dry-run ready"
}
Write-Host " Log: $LogPath"
Write-Host " Summary: D:\HermesData\state\secrets-work\bw-dedupe-apply-summary.json"
Write-Host "============================================================"
exit 0
