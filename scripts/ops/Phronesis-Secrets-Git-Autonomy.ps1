#Requires -Version 5.1
<#
.SYNOPSIS
  Phronesis Secrets + Git autonomy - interactive operator script with full logging.

.DESCRIPTION
  Consolidates scattered secrets into D:\HermesData\.env (names-only audit in log),
  optionally exports Infisical, enables Bitwarden in config.yaml, audits Git drift,
  runs backup-resilience v3 + self-recovery-watchdog, and writes a review log for Composer.

  SAFE: Never writes secret VALUES to the log file - key names and status only.

.PARAMETER Lane
  secrets | git | both | audit - skip menu when set.

.PARAMETER NonInteractive
  Run defaults without prompts (lane=audit only - safe read-only audit).

.EXAMPLE
  # Run as Administrator (recommended for Docker Infisical retire):
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\HermesData\scripts\ops\Phronesis-Secrets-Git-Autonomy.ps1

.EXAMPLE
  powershell -File D:\HermesData\scripts\ops\Phronesis-Secrets-Git-Autonomy.ps1 -Lane both
#>
param(
    [ValidateSet('secrets', 'git', 'both', 'audit')]
    [string] $Lane = '',
    [switch] $NonInteractive
)

$ErrorActionPreference = 'Continue'
$OpsDir        = $PSScriptRoot
$ScriptsRoot   = Split-Path $PSScriptRoot -Parent
$HermesRoot    = Split-Path $ScriptsRoot -Parent
$VaultRoot     = 'D:\PhronesisVault'
$LogFile       = Join-Path $OpsDir 'secrets-git-log.txt'
$SessionStamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$CanonicalEnv  = Join-Path $HermesRoot '.env'
$WorkspaceEnv  = Join-Path $HermesRoot 'hermes-workspace\.env'  # retired stub
$SecretsDir    = Join-Path $HermesRoot 'secrets'
$InfisicalDir  = 'D:\PhronesisInfisical'
$InfisicalCli  = Join-Path $env:APPDATA 'npm\infisical.cmd'
$InfisicalUrl  = 'http://192.168.1.21:8080'
$Python        = Join-Path $HermesRoot 'hermes-agent\venv\Scripts\python.exe'
$ConfigYaml    = Join-Path $HermesRoot 'config.yaml'
$EnvKeyPattern = '^([A-Za-z_][A-Za-z0-9_]*)='

New-Item -ItemType Directory -Force -Path $SecretsDir | Out-Null

$script:LogBuffer = [System.Collections.Generic.List[string]]::new()

function Write-Log {
    param([string] $Message, [string] $Level = 'INFO')
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    $script:LogBuffer.Add($line)
    switch ($Level) {
        'OK'   { Write-Host $line -ForegroundColor Green }
        'WARN' { Write-Host $line -ForegroundColor Yellow }
        'ERR'  { Write-Host $line -ForegroundColor Red }
        default { Write-Host $line }
    }
}

function Flush-Log {
    $header = @(
        "================================================================",
        " Phronesis Secrets + Git Autonomy Log",
        " Session: $SessionStamp",
        " Operator: $env:USERNAME",
        " Machine: $env:COMPUTERNAME",
        " Admin: $(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))",
        "================================================================",
        ""
    )
    $header + $script:LogBuffer | Set-Content -Path $LogFile -Encoding UTF8
    Write-Log "Log written: $LogFile" 'OK'
}

function Get-EnvKeyNames {
    param([string] $Path)
    if (-not (Test-Path $Path)) { return @() }
    $names = @()
    Get-Content $Path -ErrorAction SilentlyContinue | ForEach-Object {
        $t = $_.Trim()
        if ($t -match '^\s*#' -or [string]::IsNullOrWhiteSpace($t)) { return }
        if ($t -match $EnvKeyPattern) { $names += $Matches[1] }
    }
    return $names | Sort-Object -Unique
}

function Test-PortListening {
    param([int] $Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Invoke-SecretsLane {
    Write-Log '=== SECRETS LANE ==='

    $sources = @{
        'canonical'        = $CanonicalEnv
        'infisical_export' = Join-Path $SecretsDir 'infisical-export.env'
    }
    $allKeys = @{}
    foreach ($label in $sources.Keys) {
        $path = $sources[$label]
        $keys = Get-EnvKeyNames -Path $path
        $pathLabel = if (Test-Path $path) { $path } else { 'MISSING' }
        Write-Log "$label : $pathLabel - $($keys.Count) keys"
        if ($keys.Count -gt 0) {
            Write-Log "  keys: $($keys -join ', ')"
        }
        foreach ($k in $keys) {
            if (-not $allKeys.ContainsKey($k)) { $allKeys[$k] = @() }
            $allKeys[$k] += $label
        }
    }

    $dupes = $allKeys.GetEnumerator() | Where-Object { $_.Value.Count -gt 1 }
    if ($dupes) {
        Write-Log 'Duplicate key names across sources:' 'WARN'
        foreach ($d in $dupes) {
            Write-Log "  $($d.Key) in: $($d.Value -join ', ')" 'WARN'
        }
    }

    $doInfisical = $false
    if (-not $NonInteractive) {
        $ans = Read-Host 'Export from Infisical? (y/N) - requires browser login if not configured'
        $doInfisical = $ans -match '^[Yy]'
    }

    if ($doInfisical) {
        Write-Log 'Infisical export requested'
        if (-not (Test-Path $InfisicalCli)) {
            Write-Log "Infisical CLI not found at $InfisicalCli - run: npm install -g @infisical/cli" 'ERR'
        } else {
            $exportPath = Join-Path $SecretsDir 'infisical-export.env'
            $env:INFISICAL_DOMAIN = $InfisicalUrl
            Write-Log "INFISICAL_DOMAIN=$InfisicalUrl"
            Write-Log 'If export fails, run manually: infisical login  (browser opens)'
            Write-Log 'Then re-run this script and choose Infisical export again.'

            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $InfisicalCli
            $psi.Arguments = 'export --env=prod --path=/ --format=dotenv'
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true
            $p = [System.Diagnostics.Process]::Start($psi)
            $stdout = $p.StandardOutput.ReadToEnd()
            $stderr = $p.StandardError.ReadToEnd()
            $p.WaitForExit()
            if ($p.ExitCode -eq 0 -and $stdout) {
                $stdout | Set-Content -Path $exportPath -Encoding UTF8 -NoNewline
                $expKeys = Get-EnvKeyNames -Path $exportPath
                Write-Log "Infisical export OK: $($expKeys.Count) keys -> $exportPath" 'OK'
                Write-Log "  exported key names: $($expKeys -join ', ')"
            } else {
                Write-Log "Infisical export failed (exit $($p.ExitCode)): $($stderr.Trim())" 'ERR'
            }
        }
    }

    $mergeSources = @(
        (Join-Path $SecretsDir 'infisical-export.env')
    )
    if (-not (Test-Path $CanonicalEnv)) {
        New-Item -ItemType Directory -Force -Path $HermesRoot | Out-Null
        "# Hermes canonical secrets - managed by Phronesis-Secrets-Git-Autonomy`n" | Set-Content $CanonicalEnv -Encoding UTF8
        Write-Log "Created new canonical env: $CanonicalEnv" 'OK'
    }

    $canonicalKeys = Get-EnvKeyNames -Path $CanonicalEnv
    $merged = 0
    $canonicalLines = @(Get-Content $CanonicalEnv -ErrorAction SilentlyContinue)

    foreach ($src in $mergeSources) {
        if (-not (Test-Path $src)) { continue }
        Get-Content $src -ErrorAction SilentlyContinue | ForEach-Object {
            $line = $_.TrimEnd()
            if ($line -match '^\s*#' -or [string]::IsNullOrWhiteSpace($line)) { return }
            if ($line -match ($EnvKeyPattern + '(.*)$')) {
                $key = $Matches[1]
                if ($canonicalKeys -contains $key) { return }
                $canonicalLines += $line
                $canonicalKeys += $key
                $merged++
                Write-Log "  merged (new): $key from $(Split-Path $src -Leaf)"
            }
        }
    }

    if ($merged -gt 0) {
        $canonicalLines | Set-Content -Path $CanonicalEnv -Encoding UTF8
        Write-Log "Merged $merged new keys into $CanonicalEnv" 'OK'
    } else {
        Write-Log 'No new keys to merge into canonical .env'
    }

    $finalKeys = Get-EnvKeyNames -Path $CanonicalEnv
    Write-Log "Canonical D:\HermesData\.env now has $($finalKeys.Count) keys" 'OK'

    if (-not $NonInteractive) {
        $bw = Read-Host 'Enable Bitwarden in config.yaml? (y/N) - requires BWS_ACCESS_TOKEN in D:\HermesData\.env'
        if ($bw -match '^[Yy]') {
            $hasBws = 'BWS_ACCESS_TOKEN' -in $finalKeys
            if (-not $hasBws) {
                Write-Log 'BWS_ACCESS_TOKEN not in canonical .env - add it first, then re-run' 'WARN'
            } elseif (Test-Path $ConfigYaml) {
                $cfg = Get-Content $ConfigYaml -Raw
                $cfg = $cfg -replace '(?m)^(\s*enabled:\s*)false(\s*#.*bitwarden.*)?$', '${1}true'
                if ($cfg -notmatch 'secrets:\s*\n\s*bitwarden:') {
                    Write-Log 'config.yaml secrets.bitwarden block not found - enable manually' 'WARN'
                } else {
                    $cfg | Set-Content $ConfigYaml -Encoding UTF8 -NoNewline
                    Write-Log 'Set config.yaml secrets.bitwarden.enabled: true' 'OK'
                    Write-Log 'Restart Hermes gateway after adding BWS_ACCESS_TOKEN for pull-at-startup'
                }
            }
        }
    }

    if (-not $NonInteractive) {
        $retire = Read-Host 'Retire Infisical Docker after 48h verification? (y/N)'
        if ($retire -match '^[Yy]') {
            $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            if (-not $isAdmin) {
                Write-Log 'Retire skipped - re-run script as Administrator for docker compose down' 'WARN'
            } elseif (Test-Path (Join-Path $InfisicalDir 'docker-compose.prod.yml')) {
                Push-Location $InfisicalDir
                Write-Log 'Stopping Infisical stack...'
                & docker compose -f docker-compose.prod.yml down 2>&1 | ForEach-Object { Write-Log $_ }
                Pop-Location
                Write-Log 'Infisical containers stopped. DB volumes preserved.' 'OK'
            }
        }
    }

    $fleetKeys = @('OPENROUTER_API_KEY', 'GROQ_API_KEY', 'BRAVE_SEARCH_API_KEY', 'BWS_ACCESS_TOKEN')
    foreach ($fk in $fleetKeys) {
        $present = $fk -in $finalKeys
        Write-Log "  fleet key $fk : $(if ($present) { 'PRESENT' } else { 'MISSING' })"
    }
}

function Invoke-GitLane {
    Write-Log '=== GIT LANE ==='

    $repos = @(
        @{ Name = 'HermesData'; Path = $HermesRoot; Branch = 'main' },
        @{ Name = 'PhronesisVault'; Path = $VaultRoot; Branch = 'master' },
        @{ Name = 'PhronesisSilo'; Path = 'K:\PhronesisSilo'; Branch = 'main' }
    )

    foreach ($r in $repos) {
        $gitDir = Join-Path $r.Path '.git'
        if (-not (Test-Path $gitDir)) {
            Write-Log "$($r.Name): NO GIT at $($r.Path)" 'WARN'
            continue
        }
        Push-Location $r.Path
        $remote = (git remote get-url origin 2>$null)
        $last   = (git log -1 --format='%ci | %s' 2>$null)
        $ahead  = (git rev-list --count "origin/$($r.Branch)..HEAD" 2>$null)
        $dirty  = ((git status --porcelain 2>$null) | Measure-Object -Line).Lines
        $untracked = (git status --porcelain 2>$null | Where-Object { $_ -like '??*' } | Measure-Object -Line).Lines
        Write-Log "$($r.Name): remote=$remote"
        Write-Log "  last commit: $last"
        Write-Log "  unpushed=$ahead dirty=$dirty untracked=$untracked"
        if ($untracked -gt 0) {
            Write-Log '  untracked sample:' 'WARN'
            git status --porcelain 2>$null | Where-Object { $_ -like '??*' } | Select-Object -First 5 | ForEach-Object {
                Write-Log "    $_" 'WARN'
            }
        }
        Pop-Location
    }

    $watchdog = Join-Path $ScriptsRoot 'self-recovery-watchdog.py'
    if (Test-Path $watchdog) {
        Write-Log "Watchdog present: $watchdog" 'OK'
    } else {
        Write-Log "Watchdog missing at $watchdog" 'ERR'
    }

    if (Test-Path $Python) {
        Write-Log 'Running self-recovery-watchdog.py...'
        $wdOut = & $Python $watchdog 2>&1 | Out-String
        $wdOut.Trim().Split("`n") | ForEach-Object { if ($_) { Write-Log "  $_" } }
    }

    $backup = Join-Path $ScriptsRoot 'backup-resilience.py'
    if (Test-Path $backup) {
        $doBackup = $true
        if (-not $NonInteractive) {
            $ans = Read-Host 'Run backup-resilience v3 (commit+push allowlist paths)? (Y/n)'
            $doBackup = $ans -notmatch '^[Nn]'
        }
        if ($doBackup) {
            Write-Log 'Running backup-resilience.py v3...'
            $bkOut = & $Python $backup 2>&1 | Out-String
            $bkOut.Trim().Split("`n") | ForEach-Object { if ($_) { Write-Log "  $_" } }
        }
    }

    $cronPath = Join-Path $HermesRoot 'cron\jobs.json'
    if (Test-Path $cronPath) {
        $cron = Get-Content $cronPath -Raw | ConvertFrom-Json
        foreach ($job in @('Hermes-Resilience-Backup', 'Self-Recovery-Watchdog')) {
            $j = $cron.jobs | Where-Object { $_.name -eq $job } | Select-Object -First 1
            if ($j) {
                Write-Log "Cron $job : enabled=$($j.enabled) last=$($j.last_status) schedule=$($j.schedule_display)"
            }
        }
    }
}

function Invoke-SecretsAudit {
    Write-Log '=== SECRETS AUDIT (read-only, key names only) ==='
    $sources = @{
        'canonical'        = $CanonicalEnv
        'infisical_export' = Join-Path $SecretsDir 'infisical-export.env'
    }
    foreach ($label in $sources.Keys) {
        $path = $sources[$label]
        $keys = Get-EnvKeyNames -Path $path
        $pathLabel = if (Test-Path $path) { $path } else { 'MISSING' }
        Write-Log "$label : $pathLabel - $($keys.Count) keys"
        if ($keys.Count -gt 0) { Write-Log "  keys: $($keys -join ', ')" }
    }
    $fleetKeys = @('OPENROUTER_API_KEY', 'GROQ_API_KEY', 'BRAVE_SEARCH_API_KEY', 'BWS_ACCESS_TOKEN')
    $canon = Get-EnvKeyNames -Path $CanonicalEnv
    foreach ($fk in $fleetKeys) {
        Write-Log "  fleet key $fk : $(if ($fk -in $canon) { 'PRESENT' } else { 'MISSING' })"
    }
}

function Invoke-AuditLane {
    Write-Log '=== AUDIT ONLY (read-only) ==='
    Invoke-SecretsAudit
    Write-Log '=== GIT AUDIT (no push) ==='
    $repos = @(
        @{ Name = 'HermesData'; Path = $HermesRoot; Branch = 'main' },
        @{ Name = 'PhronesisVault'; Path = $VaultRoot; Branch = 'master' }
    )
    foreach ($r in $repos) {
        if (-not (Test-Path (Join-Path $r.Path '.git'))) { continue }
        Push-Location $r.Path
        $dirty = ((git status --porcelain 2>$null) | Measure-Object -Line).Lines
        Write-Log "$($r.Name) dirty files: $dirty"
        Pop-Location
    }

    Write-Log '=== STACK PROBE ==='
    foreach ($p in @(8090, 8091, 8642, 3001, 9119)) {
        $up = Test-PortListening -Port $p
        Write-Log "  :$p $(if ($up) { 'UP' } else { 'DOWN' })"
    }
    if (Test-Path $InfisicalCli) {
        Write-Log "Infisical CLI: $((& $InfisicalCli --version 2>&1) -join ' ')"
    }
    $containers = & docker ps --format '{{.Names}}' 2>$null
    if ($containers) {
        $inf = $containers | Where-Object { $_ -match 'infisical|agent-vault' }
        Write-Log "Infisical containers: $(if ($inf) { $inf -join ', ' } else { 'none running' })"
    }
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' Phronesis Secrets + Git Autonomy' -ForegroundColor Cyan
Write-Host " Log -> $LogFile" -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

Write-Log "Session $SessionStamp started"

if (-not $Lane -and -not $NonInteractive) {
    Write-Host 'Choose lane:'
    Write-Host '  [1] Secrets only  (audit, Infisical export, merge canonical .env)'
    Write-Host '  [2] Git only      (drift audit, watchdog, backup-resilience v3)'
    Write-Host '  [3] Both          (secrets then git)'
    Write-Host '  [4] Audit only    (read-only - safe default)'
    $choice = Read-Host 'Enter 1-4 (default 4)'
    switch ($choice) {
        '1' { $Lane = 'secrets' }
        '2' { $Lane = 'git' }
        '3' { $Lane = 'both' }
        default { $Lane = 'audit' }
    }
}

if ($NonInteractive -and -not $Lane) { $Lane = 'audit' }
if (-not $Lane) { $Lane = 'audit' }

Write-Log "Lane: $Lane"

switch ($Lane) {
    'secrets' { Invoke-SecretsLane }
    'git'     { Invoke-GitLane }
    'both'    { Invoke-SecretsLane; Invoke-GitLane }
    'audit'   { Invoke-AuditLane }
}

Write-Log '=== VERIFICATION COMMANDS (for Composer review) ==='
Write-Log "  Get-Content $LogFile"
Write-Log '  D:\HermesData\scripts\run-model-management-agent.ps1 -Tick -Summary'
Write-Log '  D:\HermesData\hermes-agent\venv\Scripts\python.exe D:\HermesData\scripts\external_fleet_manager.py --health --shadow'
Write-Log '  curl http://127.0.0.1:3001/api/auth-check  (Hub hard-refresh Ctrl+Shift+R)'
Write-Log '  git -C D:\HermesData status -sb'
Write-Log '  git -C D:\PhronesisVault status -sb'

Flush-Log

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " Done. Review log: $LogFile" -ForegroundColor Green
Write-Host ' Share this file with Composer for full session review.' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''
if (-not $NonInteractive) {
    Read-Host 'Press Enter to close'
}