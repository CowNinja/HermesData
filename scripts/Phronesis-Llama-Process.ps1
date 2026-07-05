# Phronesis-Llama-Process.ps1 - Port-scoped llama-server management (Ollama-safe on Windows).
# Never use Stop-Process -Name llama-server when Ollama may be running on another port.

function Get-PhronesisLlamaCore {
    $corePath = Join-Path $PSScriptRoot "phronesis-core.json"
    if (Test-Path $corePath) { return Get-Content $corePath -Raw | ConvertFrom-Json }
    return $null
}

function Get-LlamaPortListenerPid {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return $null
}

function Stop-LlamaOnPort {
    param([int]$Port = 8090)
    $listener = Get-LlamaPortListenerPid -Port $Port
    if (-not $listener) { return 0 }
    Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
    return 1
}

function Get-PhronesisLlamaProcesses {
    $core = Get-PhronesisLlamaCore
    $markers = @('PhronesisModels')
    if ($core -and $core.llama_exe) {
        $exe = [string]$core.llama_exe
        $leaf = Split-Path $exe -Leaf
        if ($leaf) { $markers += $leaf }
        $dir = Split-Path $exe -Parent
        if ($dir -and $dir -notin $markers) { $markers += $dir }
    }
    $seen = @{}
    $out = @()
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'llama-server.exe' } |
        ForEach-Object {
            $cmd = [string]$_.CommandLine
            $match = $false
            foreach ($m in $markers) {
                if ($cmd -like "*$m*") { $match = $true; break }
            }
            if ($match -and -not $seen[$_.ProcessId]) {
                $seen[$_.ProcessId] = $true
                $out += $_
            }
        }
    return $out
}

function Remove-DuplicatePhronesisLlamas {
    param([int]$RouterPort = 8090)
    $keep = Get-LlamaPortListenerPid -Port $RouterPort
    $killed = 0
    foreach ($p in (Get-PhronesisLlamaProcesses)) {
        if ($keep -and [int]$p.ProcessId -eq $keep) { continue }
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
    return $killed
}