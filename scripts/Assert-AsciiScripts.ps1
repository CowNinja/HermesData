# Assert-AsciiScripts.ps1
# Fails if executable scripts contain non-ASCII bytes.
# Windows PowerShell 5.1 often breaks on smart quotes, em-dashes, arrows, and
# box-drawing chars unless the file has a UTF-8 BOM and the shell is UTF-8 aware.
#
# Usage:
#   .\Assert-AsciiScripts.ps1
#   .\Assert-AsciiScripts.ps1 -Paths D:\ComfyUI,D:\HermesData\scripts
#   .\Assert-AsciiScripts.ps1 -ShowSamples
#
param(
    [string[]]$Paths = @(
        'D:\HermesData\scripts',
        'D:\ComfyUI'
    ),
    [string[]]$Extensions = @('.ps1', '.bat', '.cmd', '.vbs', '.sh'),
    [switch]$ShowSamples
)

$ErrorActionPreference = 'Stop'
$violations = @()

function Test-FileAscii {
    param([string]$FilePath)
    $bytes = [System.IO.File]::ReadAllBytes($FilePath)
    $offenders = @()
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        $b = $bytes[$i]
        if ($b -eq 9 -or $b -eq 10 -or $b -eq 13) { continue }  # tab/lf/cr
        if ($b -lt 32 -or $b -gt 126) {
            $offenders += [pscustomobject]@{
                Offset = $i
                Byte   = $b
                Char   = if ($b -ge 128) { 'U+' + $b.ToString('X4') } else { [char]$b }
            }
        }
    }
    return $offenders
}

foreach ($root in $Paths) {
    if (-not (Test-Path $root)) { continue }
    $files = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $Extensions -contains $_.Extension.ToLower() }

    foreach ($file in $files) {
        $hits = Test-FileAscii -FilePath $file.FullName
        if ($hits.Count -gt 0) {
            $violations += [pscustomobject]@{
                File  = $file.FullName
                Count = $hits.Count
                First = $hits | Select-Object -First 3
            }
        }
    }
}

if ($violations.Count -eq 0) {
    Write-Host "OK: all scanned scripts are ASCII-only."
    exit 0
}

Write-Host "FAIL: $($violations.Count) script(s) contain non-ASCII bytes."
foreach ($v in $violations) {
    Write-Host "  $($v.File) ($($v.Count) bytes)"
    if ($ShowSamples) {
        foreach ($sample in $v.First) {
            Write-Host "    offset $($sample.Offset): byte $($sample.Byte) ($($sample.Char))"
        }
    }
}

Write-Host ""
Write-Host "Rule: .ps1 .bat .cmd .vbs .sh must be 7-bit ASCII (printable + tab/newline)."
Write-Host "Use - for dashes, -> for arrows, [OK]/[WARN] for status - not unicode punctuation."
Write-Host ""
Write-Host "Auto-fix: python D:\HermesData\scripts\repair_ascii_scripts.py --paths D:\HermesData\scripts"
Write-Host "Or:       powershell -File D:\HermesData\scripts\Phronesis.ps1 doctor"
exit 1