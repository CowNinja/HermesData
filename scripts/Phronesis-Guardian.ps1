# Locked schtask launches: powershell.exe -File this script (cannot rebind TR).
# Exit in milliseconds after starting real work via pythonw + CREATE_NO_WINDOW.
$ErrorActionPreference = "SilentlyContinue"
if ($env:HERMES_HIDDEN_CHILD -eq "1") {
    & (Join-Path $PSScriptRoot "Phronesis-Guardian-Body.ps1")
    exit $LASTEXITCODE
}
$pyw = "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe"
$launcher = "D:\HermesData\scripts\launch_hidden_ps.py"
$body = "D:\HermesData\scripts\Phronesis-Guardian-Body.ps1"
if (-not (Test-Path $pyw)) {
    $pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
}
$cmd = '"' + $pyw + '" "' + $launcher + '" "' + $body + '"'
try {
    $w = New-Object -ComObject WScript.Shell
    $null = $w.Run($cmd, 0, $false)
} catch {
    Start-Process -FilePath $pyw -ArgumentList @($launcher, $body) -WindowStyle Hidden | Out-Null
}
exit 0
