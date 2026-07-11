# Bitwarden unlock + metadata dump for Hermes deconflict
# ASCII only. Prefer normal PowerShell (not Run as Administrator).
#
# Remote-friendly (no interactive prompt):
#   $env:BW_PASSWORD = 'your-master-password'
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\HermesData\scripts\bw_unlock_and_dump_meta.ps1
#   Remove-Item Env:BW_PASSWORD
#
# Interactive (local console that supports Read-Host):
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\HermesData\scripts\bw_unlock_and_dump_meta.ps1
#
# Optional:
#   -Password '...'   (avoid if command history is a concern; prefer env var)

param(
    [string]$Password = ""
)

$ErrorActionPreference = "Continue"

$BwCmd = "D:\HermesData\bin\bw.cmd"
$OutDir = "D:\HermesData\state\secrets-work"
$LogPath = Join-Path $OutDir "bw-meta-dump.txt"
$JsonPath = Join-Path $OutDir "bw-items-safe.json"
$SessionPath = Join-Path $OutDir "bw-session.txt"
$ReportPath = "D:\PhronesisVault\Operations\logs\bitwarden-deconflict-report-latest.md"
$ReportPath2 = Join-Path $OutDir "bw-deconflict-report.md"

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding Ascii -ErrorAction SilentlyContinue } catch {}
    Write-Host $line
}

function Get-HostFromUri {
    param([string]$Uri)
    if ([string]::IsNullOrWhiteSpace($Uri)) { return "" }
    try {
        $u = $Uri.Trim()
        if ($u -notmatch "://") { $u = "https://" + $u }
        $parsed = [Uri]$u
        $h = $parsed.Host.ToLowerInvariant()
        if ($h.StartsWith("www.")) { $h = $h.Substring(4) }
        return $h
    } catch { return "" }
}

if (-not (Test-Path -LiteralPath $BwCmd)) {
    Write-Host "ERROR: bw launcher not found at $BwCmd"
    exit 1
}

try { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null } catch {
    Write-Host "ERROR: cannot create $OutDir"
    exit 1
}

Set-Content -LiteralPath $LogPath -Value "BW meta dump start" -Encoding Ascii
Write-Log "script_start"
Write-Host ""
Write-Host "Bitwarden metadata dump (no passwords written to output files)"
Write-Host "Log: $LogPath"
Write-Host ""

try {
    $st = & $BwCmd status 2>&1 | Out-String
    Write-Log ("pre_status=" + $st.Trim())
} catch {
    Write-Log ("pre_status_error=" + $_.Exception.Message)
}

# Resolve master password: -Password param > env BW_PASSWORD > interactive Read-Host
$plain = ""
if (-not [string]::IsNullOrWhiteSpace($Password)) {
    $plain = $Password
    Write-Log "password_source=param"
} elseif (-not [string]::IsNullOrWhiteSpace($env:BW_PASSWORD)) {
    $plain = $env:BW_PASSWORD
    Write-Log "password_source=env_BW_PASSWORD"
} else {
    Write-Host ""
    Write-Host "No BW_PASSWORD env and no -Password. Trying interactive prompt..."
    Write-Host "(Remote sessions often cannot show this prompt - set env BW_PASSWORD instead.)"
    try {
        $secure = Read-Host -AsSecureString "Master password"
        if ($null -ne $secure) {
            $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try {
                $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            } finally {
                [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
            }
        }
        Write-Log "password_source=read_host"
    } catch {
        Write-Log ("read_host_failed=" + $_.Exception.Message)
    }
}

if ([string]::IsNullOrWhiteSpace($plain)) {
    Write-Log "ERROR no password available"
    Write-Host ""
    Write-Host "ERROR: No password. For remote PowerShell run:"
    Write-Host '  $env:BW_PASSWORD = ''your-master-password'''
    Write-Host '  powershell -NoProfile -ExecutionPolicy Bypass -File D:\HermesData\scripts\bw_unlock_and_dump_meta.ps1'
    Write-Host '  Remove-Item Env:BW_PASSWORD'
    exit 1
}

$env:BW_PASSWORD = $plain
$plain = $null
$Password = $null

Write-Host "Unlocking vault..."
$session = ""
try {
    $unlockOut = & $BwCmd unlock --passwordenv BW_PASSWORD --raw 2>&1
    if ($unlockOut -is [System.Array]) {
        $session = ($unlockOut | ForEach-Object { "$_" }) -join "`n"
    } else {
        $session = [string]$unlockOut
    }
    $session = $session.Trim()
    $lines = @($session -split "(`r`n|`n)" | Where-Object { $_ -and $_.Trim().Length -gt 0 })
    if ($lines.Count -gt 0) { $session = $lines[-1].Trim() }
} catch {
    Write-Log ("unlock_exception=" + $_.Exception.Message)
    $session = ""
}

Remove-Item Env:BW_PASSWORD -ErrorAction SilentlyContinue

if ([string]::IsNullOrWhiteSpace($session) -or $session.Length -lt 20 -or $session -match "Invalid|Error|password") {
    Write-Log ("unlock_failed=" + $session)
    Write-Host "Unlock failed. See log: $LogPath"
    exit 2
}

try { Set-Content -LiteralPath $SessionPath -Value $session -Encoding Ascii -NoNewline } catch {
    Write-Log ("session_write_error=" + $_.Exception.Message)
}
$env:BW_SESSION = $session
Write-Log ("session_len=" + $session.Length)

$statusJson = ""
try { $statusJson = (& $BwCmd status --session $session 2>&1 | Out-String).Trim() } catch {
    Write-Log ("status_error=" + $_.Exception.Message)
}
Write-Log ("status=" + $statusJson)
Write-Host $statusJson

if ($statusJson -notmatch '"status"\s*:\s*"unlocked"') {
    Write-Log "ERROR vault not unlocked"
    Write-Host "Vault not unlocked. Exiting."
    exit 3
}

Write-Host "Syncing..."
try {
    $syncOut = (& $BwCmd sync --session $session 2>&1 | Out-String).Trim()
    Write-Log ("sync=" + $syncOut)
} catch { Write-Log ("sync_error=" + $_.Exception.Message) }

Write-Host "Listing items..."
$itemsRaw = ""
try { $itemsRaw = (& $BwCmd list items --session $session 2>&1 | Out-String).Trim() } catch {
    Write-Log ("list_exception=" + $_.Exception.Message)
    exit 4
}
if (-not $itemsRaw.StartsWith("[")) {
    $preview = $itemsRaw; if ($preview.Length -gt 400) { $preview = $preview.Substring(0, 400) }
    Write-Log ("list_items_failed=" + $preview)
    exit 4
}

try { $items = $itemsRaw | ConvertFrom-Json } catch {
    Write-Log ("json_parse_error=" + $_.Exception.Message)
    exit 4
}
if ($null -eq $items) { exit 4 }
if ($items -isnot [System.Array]) { $items = @($items) }

Write-Log ("total_items=" + $items.Count)

$loginCount = 0; $noteCount = 0; $cardCount = 0; $identCount = 0
$safe = New-Object System.Collections.Generic.List[object]
$clusters = @{}

foreach ($it in $items) {
    $t = 0
    try { $t = [int]$it.type } catch { $t = 0 }
    if ($t -eq 1) { $loginCount++ }
    elseif ($t -eq 2) { $noteCount++ }
    elseif ($t -eq 3) { $cardCount++ }
    elseif ($t -eq 4) { $identCount++ }

    $user = ""; $hosts = New-Object System.Collections.Generic.List[string]
    $hasPw = $false; $hasTotp = $false
    if ($null -ne $it.login) {
        $login = $it.login
        if ($null -ne $login.username) { $user = ([string]$login.username).Trim().ToLowerInvariant() }
        if (-not [string]::IsNullOrEmpty([string]$login.password)) { $hasPw = $true }
        if (-not [string]::IsNullOrEmpty([string]$login.totp)) { $hasTotp = $true }
        if ($null -ne $login.uris) {
            foreach ($u in @($login.uris)) {
                $uri = $null
                if ($u -is [string]) { $uri = $u }
                elseif ($null -ne $u.uri) { $uri = [string]$u.uri }
                $h = Get-HostFromUri -Uri ([string]$uri)
                if ($h -and -not $hosts.Contains($h)) { $hosts.Add($h) }
            }
        }
    }
    $hostArr = @($hosts | Sort-Object)
    $hostKey = ""; if ($hostArr.Count -gt 0) { $hostKey = [string]$hostArr[0] }

    $safe.Add([PSCustomObject]@{
        id = $it.id; name = $it.name; type = $t; folderId = $it.folderId
        revisionDate = $it.revisionDate; username = $user; hosts = $hostArr
        has_password = $hasPw; has_totp = $hasTotp
    }) | Out-Null

    if ($t -eq 1) {
        $fp = $hostKey + "|" + $user
        if (-not $clusters.ContainsKey($fp)) { $clusters[$fp] = New-Object System.Collections.Generic.List[string] }
        $clusters[$fp].Add([string]$it.name) | Out-Null
    }
}

Write-Log ("logins=" + $loginCount)
Write-Log ("secure_notes=" + $noteCount)
Write-Log ("cards=" + $cardCount)
Write-Log ("identities=" + $identCount)

try {
    $safe | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $JsonPath -Encoding Ascii
    Write-Log ("safe_json=" + $JsonPath)
} catch { Write-Log ("safe_json_error=" + $_.Exception.Message) }

$dupes = New-Object System.Collections.Generic.List[object]
foreach ($k in $clusters.Keys) {
    $names = $clusters[$k]
    if ($names.Count -gt 1 -and $k -ne "|") {
        $dupes.Add([PSCustomObject]@{ fingerprint = $k; count = $names.Count; names = ($names -join "; ") }) | Out-Null
    }
}
$dupesSorted = @($dupes | Sort-Object -Property count -Descending)
Write-Log ("duplicate_clusters=" + $dupesSorted.Count)

$rb = New-Object System.Text.StringBuilder
[void]$rb.AppendLine("# Bitwarden de-conflict report")
[void]$rb.AppendLine("")
[void]$rb.AppendLine("Generated: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
[void]$rb.AppendLine("")
[void]$rb.AppendLine("Total items: **" + $items.Count + "**")
[void]$rb.AppendLine("Logins: **" + $loginCount + "**")
[void]$rb.AppendLine("Secure notes: **" + $noteCount + "**")
[void]$rb.AppendLine("Cards: **" + $cardCount + "**")
[void]$rb.AppendLine("Identities: **" + $identCount + "**")
[void]$rb.AppendLine("Duplicate clusters (host+username): **" + $dupesSorted.Count + "**")
[void]$rb.AppendLine("")
[void]$rb.AppendLine("## Top duplicate clusters")
[void]$rb.AppendLine("")
[void]$rb.AppendLine("| Count | Fingerprint (host/user) | Names (sample) |")
[void]$rb.AppendLine("|------:|-------------------------|----------------|")
foreach ($d in ($dupesSorted | Select-Object -First 40)) {
    $fp = ([string]$d.fingerprint); if ($fp.Length -gt 60) { $fp = $fp.Substring(0, 60) }
    $nm = ([string]$d.names); if ($nm.Length -gt 80) { $nm = $nm.Substring(0, 80) }
    $fp = $fp.Replace("|", "/"); $nm = $nm.Replace("|", "/")
    [void]$rb.AppendLine("| " + $d.count + " | " + $fp + " | " + $nm + " |")
}
[void]$rb.AppendLine("")
[void]$rb.AppendLine("## Files")
[void]$rb.AppendLine("")
[void]$rb.AppendLine("- Log: " + $LogPath)
[void]$rb.AppendLine("- Safe items JSON: " + $JsonPath)
[void]$rb.AppendLine("- Session file (local): " + $SessionPath)
[void]$rb.AppendLine("")
[void]$rb.AppendLine("No passwords, TOTP, or note bodies in these files.")
[void]$rb.AppendLine("")

$reportText = $rb.ToString()
try {
    [System.IO.File]::WriteAllText($ReportPath, $reportText)
    [System.IO.File]::WriteAllText($ReportPath2, $reportText)
    Write-Log ("report=" + $ReportPath)
} catch { Write-Log ("report_write_error=" + $_.Exception.Message) }

Write-Host ""
Write-Host "DONE. Tell Hermes: bw dump ready"
Write-Host ("Dupes: " + $dupesSorted.Count)
Write-Host ("Log: " + $LogPath)
Write-Log "DONE ok"
exit 0
