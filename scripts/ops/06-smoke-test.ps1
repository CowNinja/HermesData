# 06-smoke-test.ps1 — End-to-end test: proxy -> llama.cpp -> response (bulletproof v1)
# Usage:  D:\HermesData\scripts\ops\06-smoke-test.ps1 [-LongTest]

param(
    [switch]$LongTest = $false
)

$ErrorActionPreference = "Continue"
$MaxRetries = 2
$RetryPauseSec = 5

if ($LongTest) {
    $prompt = "Write a Python function that computes the first 20 Fibonacci numbers. Include type hints and a docstring."
    $maxTokens = 500
} else {
    $prompt = "Say OK in two words."
    $maxTokens = 10
}

Write-Host "Sending test prompt to proxy (8091)..." -ForegroundColor Yellow

$body = @{
    model      = "phronesis-sovereign-auto"
    messages   = @(@{ role = "user"; content = $prompt })
    max_tokens = $maxTokens
} | ConvertTo-Json -Depth 10

$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$lastError = $null

for ($attempt = 0; $attempt -le $MaxRetries; $attempt++) {
    if ($attempt -gt 0) {
        Write-Host "Retry $attempt/$MaxRetries after ${RetryPauseSec}s (transient connection error)..." -ForegroundColor Yellow
        Start-Sleep -Seconds $RetryPauseSec
    }

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8091/v1/chat/completions" `
            -Method POST -ContentType "application/json" -Body $bodyBytes -TimeoutSec 120 -UseBasicParsing
        $sw.Stop()

        $json = $r.Content | ConvertFrom-Json
        $content = $json.choices[0].message.content
        $model   = $json.model
        $usage   = $json.usage

        Write-Host "`n=== SMOKE TEST PASSED ===" -ForegroundColor Green
        if ($attempt -gt 0) { Write-Host "(passed on retry $attempt)" -ForegroundColor DarkGreen }
        Write-Host "Model:    $model" -ForegroundColor Cyan
        Write-Host "Time:     $($sw.ElapsedMilliseconds)ms" -ForegroundColor Cyan
        Write-Host "Tokens:   prompt=$($usage.prompt_tokens) completion=$($usage.completion_tokens) total=$($usage.total_tokens)" -ForegroundColor Cyan
        Write-Host "Response: $content" -ForegroundColor White

        if ($usage.completion_tokens -gt 0) {
            $tokPerSec = [math]::Round($usage.completion_tokens / ($sw.ElapsedMilliseconds / 1000), 1)
            Write-Host "~$tokPerSec tok/s (estimated)" -ForegroundColor DarkCyan
        }
        exit 0
    } catch {
        $sw.Stop()
        $lastError = $_
        $msg = $_.Exception.Message
        $transient = $msg -match 'unexpected error occurred on a receive|connection was closed|Unable to connect'
        if (-not $transient -or $attempt -eq $MaxRetries) { break }
    }
}

Write-Host "`n=== SMOKE TEST FAILED ===" -ForegroundColor Red
Write-Host "Error: $lastError" -ForegroundColor Red
Write-Host "`nTry running 04-status.ps1 to see what's down." -ForegroundColor Yellow
exit 1