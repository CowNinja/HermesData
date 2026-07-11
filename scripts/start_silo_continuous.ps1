# Start resource-aware continuous silo builder (non-elevated).
# Stop: create D:\HermesData\state\silo_continuous.STOP
$ErrorActionPreference = "Continue"
$py = "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$script = "D:\HermesData\scripts\silo_continuous_loop.py"
$stop = "D:\HermesData\state\silo_continuous.STOP"
if (Test-Path $stop) { Remove-Item $stop -Force }
Write-Host "Starting continuous silo loop. Stop file: $stop"
& $py $script --max-cycles 0
