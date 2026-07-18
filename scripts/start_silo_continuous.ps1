# Start resource-aware continuous silo builder (non-elevated, no console flash).
# Stop: create D:\HermesData\state\silo_continuous.STOP
$ErrorActionPreference = "Continue"
$pyw = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"
$py = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }
if (-not (Test-Path $pyw)) { $pyw = "pythonw" }
$script = "D:\HermesData\scripts\silo_continuous_loop.py"
$stop = "D:\HermesData\state\silo_continuous.STOP"
$out = "D:\HermesData\state\silo_continuous_stdout.log"
$err = "D:\HermesData\state\silo_continuous_stderr.log"
if (Test-Path $stop) { Remove-Item $stop -Force }

$forkGuard = "D:\HermesData\scripts\Phronesis-ForkGuard.ps1"
if (Test-Path $forkGuard) {
    . $forkGuard
    Write-Host "Starting continuous silo loop (hidden). Stop file: $stop"
    $null = Start-HiddenProcess -FilePath $pyw `
        -ArgumentList @($script, "--max-cycles", "0", "--force-mode", "aggressive") `
        -WorkingDirectory "D:\HermesData"
} else {
    # Fallback: still hide window
    Start-Process -FilePath $pyw -ArgumentList @($script, "--max-cycles", "0", "--force-mode", "aggressive") `
        -WorkingDirectory "D:\HermesData" -WindowStyle Hidden
    Write-Host "Starting continuous silo loop (WindowStyle Hidden). Stop file: $stop"
}
