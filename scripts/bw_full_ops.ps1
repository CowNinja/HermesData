# ==============================================================================
# Bitwarden FULL OPS for Hermes (ASCII only)
# Pattern used by most CLI automations:
#   login/unlock with session -> bw list items to file -> analyze with Python
# PowerShell = auth + dump. Python = de-dupe math (reliable).
# NO passwords in output files. Raw dump deleted after analysis.
#
# RUN:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_full_ops.ps1"
#
# REMOTE:
#   $env:BW_EMAIL = 'mr.jeffrey.j.bloom@gmail.com'
#   $env:BW_PASSWORD = 'your-master-password'
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_full_ops.ps1"
#   Remove-Item Env:BW_PASSWORD
# ==============================================================================

param(
    [string]$Password = "",
    [string]$Email = "",
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
$AnalyzePy = "D:\HermesData\scripts\bw_analyze_from_raw.py"
$OutDir = "D:\HermesData\state\secrets-work"
$LogPath = Join-Path $OutDir "bw-full-ops-log.txt"
$SessionPath = Join-Path $OutDir "bw-session.txt"
$RawPath = Join-Path $OutDir "bw-items-raw.json"
$DefaultEmail = "mr.jeffrey.j.bloom@gmail.com"

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    try {
        Add-Content -LiteralPath $LogPath -Value $line -Encoding Ascii -ErrorAction SilentlyContinue
    } catch {}
    Write-Host $line
}

function Get-PlainPassword {
    param([string]$ParamPassword)
    if (-not [string]::IsNullOrWhiteSpace($ParamPassword)) {
        Write-Log "password_source=param"
        return $ParamPassword.Trim()
    }
    if (-not [string]::IsNullOrWhiteSpace($env:BW_PASSWORD)) {
        Write-Log "password_source=env"
        return $env:BW_PASSWORD.Trim()
    }
    Write-Host ""
    Write-Host "Enter Bitwarden MASTER PASSWORD (hidden)..."
    Write-Host "If prompt does not appear, use env BW_PASSWORD (see script header)."
    try {
        $secure = Read-Host -AsSecureString "Master password"
        if ($null -eq $secure) { return "" }
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $p = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            Write-Log "password_source=read_host"
            return $p.Trim()
        } finally {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
        }
    } catch {
        Write-Log ("read_host_error=" + $_.Exception.Message)
        return ""
    }
}

# --- bootstrap ---
try {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
} catch {
    Write-Host "ERROR: cannot create $OutDir"
    exit 1
}

Set-Content -LiteralPath $LogPath -Value "BW full ops start" -Encoding Ascii
Write-Log "script_start"
Write-Log ("bw_cmd=" + $BwCmd)
Write-Host ""
Write-Host "============================================================"
Write-Host " Bitwarden FULL OPS (CLI dump + Python analyze)"
Write-Host "============================================================"
Write-Host ""

if (-not (Test-Path -LiteralPath $BwCmd)) {
    Write-Log "ERROR bw not found"
    Write-Host "ERROR: bw CLI not found"
    exit 1
}
if (-not (Test-Path -LiteralPath $AnalyzePy)) {
    Write-Log "ERROR analyze script missing"
    Write-Host "ERROR: missing $AnalyzePy"
    exit 1
}

try {
    $ver = & $BwCmd --version 2>&1 | Out-String
    Write-Log ("bw_version=" + $ver.Trim())
} catch {
    Write-Log ("bw_version_error=" + $_.Exception.Message)
}

try {
    $pre = & $BwCmd status 2>&1 | Out-String
    Write-Log ("pre_status=" + $pre.Trim())
} catch {
    Write-Log ("pre_status_error=" + $_.Exception.Message)
}

if ([string]::IsNullOrWhiteSpace($Email)) {
    if (-not [string]::IsNullOrWhiteSpace($env:BW_EMAIL)) { $Email = $env:BW_EMAIL }
    else { $Email = $DefaultEmail }
}
Write-Log ("email=" + $Email)

$plain = Get-PlainPassword -ParamPassword $Password
if ([string]::IsNullOrWhiteSpace($plain)) {
    Write-Log "ERROR no password"
    Write-Host "ERROR: No password. Remote:"
    Write-Host '  $env:BW_EMAIL = ''mr.jeffrey.j.bloom@gmail.com'''
    Write-Host '  $env:BW_PASSWORD = ''your-master-password'''
    Write-Host '  powershell -NoProfile -ExecutionPolicy Bypass -File "D:\HermesData\scripts\bw_full_ops.ps1"'
    Write-Host '  Remove-Item Env:BW_PASSWORD'
    exit 1
}
Write-Log ("password_len=" + $plain.Length)

# --- re-login after web password changes ---
if (-not $SkipRelogin) {
    Write-Host "Logout (refresh CLI keys after password change)..."
    try {
        $lo = & $BwCmd logout 2>&1 | Out-String
        Write-Log ("logout=" + $lo.Trim())
    } catch {
        Write-Log ("logout_error=" + $_.Exception.Message)
    }

    Write-Host "Login..."
    $env:BW_PASSWORD = $plain
    try {
        # Official pattern: bw login EMAIL --passwordenv BW_PASSWORD
        $loginOut = & $BwCmd login $Email --passwordenv BW_PASSWORD 2>&1 | Out-String
        Write-Log ("login_out=" + $loginOut.Trim())
    } catch {
        Write-Log ("login_exception=" + $_.Exception.Message)
        $loginOut = ""
    }

    if ($loginOut -match "Invalid master password|Email or password is incorrect|Cryptography error") {
        Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue
        $plain = $null
        Write-Host "LOGIN FAILED. Check password. See log."
        exit 2
    }
}

# --- unlock (official: BW_SESSION from unlock --raw) ---
Write-Host "Unlock..."
$env:BW_PASSWORD = $plain
$session = ""
try {
    $unlockOut = & $BwCmd unlock --passwordenv BW_PASSWORD --raw 2>&1
    if ($unlockOut -is [System.Array]) {
        $session = ($unlockOut | ForEach-Object { "$_" }) -join "`n"
    } else {
        $session = [string]$unlockOut
    }
    $session = $session.Trim()
    $parts = @($session -split "(`r`n|`n)" | Where-Object { $_.Trim().Length -gt 0 })
    if ($parts.Count -gt 0) { $session = $parts[-1].Trim() }
} catch {
    Write-Log ("unlock_exception=" + $_.Exception.Message)
    $session = ""
}
Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue
$plain = $null
$Password = $null

if ($session.Length -lt 20 -or $session -match "Cryptography error|Invalid master password|decryption") {
    Write-Log ("unlock_failed=" + $session)
    Write-Host "UNLOCK FAILED. See log."
    exit 2
}
Write-Log ("session_len=" + $session.Length)

try {
    Set-Content -LiteralPath $SessionPath -Value $session -Encoding Ascii -NoNewline
    Write-Log ("session_file=" + $SessionPath)
} catch {
    Write-Log ("session_write_error=" + $_.Exception.Message)
}

$env:BW_SESSION = $session

# status / sync using env session (Bitwarden docs pattern)
Write-Host "Status..."
try {
    $st = & $BwCmd status 2>&1 | Out-String
    Write-Log ("status=" + $st.Trim())
    Write-Host $st
    if ($st -notmatch '"status"\s*:\s*"unlocked"') {
        # fallback explicit --session
        $st2 = & $BwCmd status --session $session 2>&1 | Out-String
        Write-Log ("status_session=" + $st2.Trim())
        if ($st2 -notmatch '"status"\s*:\s*"unlocked"') {
            Write-Host "Not unlocked. Exiting."
            exit 3
        }
    }
} catch {
    Write-Log ("status_error=" + $_.Exception.Message)
    exit 3
}

Write-Host "Sync..."
try {
    $sync = & $BwCmd sync 2>&1 | Out-String
    Write-Log ("sync=" + $sync.Trim())
    Write-Host $sync
} catch {
    Write-Log ("sync_error=" + $_.Exception.Message)
}

# --- dump items to file (official list items) ---
Write-Host "Exporting item list to file (may take a minute)..."
try {
    # Prefer --session flag for reliability in some hosts
    $raw = & $BwCmd list items --session $session 2>&1 | Out-String
    $raw = $raw.Trim()
    if (-not $raw.StartsWith("[")) {
        $ix = $raw.IndexOf("[")
        if ($ix -ge 0) { $raw = $raw.Substring($ix) }
    }
    if (-not $raw.StartsWith("[")) {
        Write-Log ("list_failed_preview=" + $raw.Substring(0, [Math]::Min(400, $raw.Length)))
        Write-Host "list items failed."
        exit 4
    }
    # Write UTF8 without BOM if possible
    [System.IO.File]::WriteAllText($RawPath, $raw)
    Write-Log ("raw_bytes=" + (Get-Item -LiteralPath $RawPath).Length)
    Write-Log ("raw_path=" + $RawPath)
} catch {
    Write-Log ("list_exception=" + $_.Exception.Message)
    Write-Host "list items exception."
    exit 4
}

# --- Python analyze (rock solid de-dupe) ---
Write-Host "Analyzing with Python (de-dupe plan)..."
try {
    $pyOut = & $Python $AnalyzePy $RawPath 2>&1 | Out-String
    Write-Log ("python_out=" + $pyOut.Trim())
    Write-Host $pyOut
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        Write-Log ("python_exit=" + $LASTEXITCODE)
        # try py launcher
        $pyOut2 = & py -3 $AnalyzePy $RawPath 2>&1 | Out-String
        Write-Log ("python_out2=" + $pyOut2.Trim())
        Write-Host $pyOut2
    }
} catch {
    Write-Log ("python_exception=" + $_.Exception.Message)
    Write-Host "Python analyze failed. Raw kept at $RawPath for Hermes."
    exit 5
}

# clear session env
Remove-Item Env:BW_SESSION -ErrorAction SilentlyContinue

Write-Log "DONE ok"
Write-Host ""
Write-Host "============================================================"
Write-Host " DONE - tell Hermes: bw full ops ready"
Write-Host " Outputs in: $OutDir"
Write-Host "============================================================"
exit 0
