# 08-download-model.ps1 - Download a GGUF from HuggingFace or direct URL
# Usage (HuggingFace):
#   D:\HermesData\scripts\ops\08-download-model.ps1 -Repo "empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF" -File "Qwythos-9B-Claude-Mythos-5-1M-Q5_K_M.gguf"
#
# Usage (direct URL):
#   D:\HermesData\scripts\ops\08-download-model.ps1 -Url "https://huggingface.co/.../resolve/main/model.gguf"

param(
    [string]$Repo,
    [string]$File,
    [string]$Url,
    [string]$OutputDir = "D:\PhronesisModels\models\candidates"
)

$ErrorActionPreference = "Stop"

# Validate args
if ($Url -and ($Repo -or $File)) { Write-Host "ERROR: Use -Url OR (-Repo + -File), not both." -ForegroundColor Red; exit 1 }
if (-not $Url -and (-not $Repo -or -not $File)) { Write-Host "ERROR: Provide -Url OR (-Repo + -File)." -ForegroundColor Red; exit 1 }

if ($Url) {
    # --- Direct URL download via Invoke-WebRequest ---
    $outFile = Join-Path $OutputDir ($Url.Split("/")[-1])
    Write-Host "Downloading from direct URL..." -ForegroundColor Yellow
    Write-Host "  Source: $Url"
    Write-Host "  Dest:   $outFile"

    if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null }

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-WebRequest -Uri $Url -OutFile $outFile -UseBasicParsing
        $sw.Stop()
        $sizeMB = [math]::Round((Get-Item $outFile).Length / 1MB, 0)
        Write-Host "Download complete: $sizeMB MB in $($sw.Elapsed.ToString('mm\:ss'))" -ForegroundColor Green
    } catch {
        Write-Host "Download failed: $_" -ForegroundColor Red
        exit 1
    }
} else {
    # --- HuggingFace download via huggingface-cli ---
    $outFile = Join-Path $OutputDir $File
    Write-Host "Downloading from HuggingFace..." -ForegroundColor Yellow
    Write-Host "  Repo: $Repo"
    Write-Host "  File: $File"
    Write-Host "  Dest: $outFile"

    if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null }

    # Check hf CLI is available
    $hfCli = Get-Command "hf" -ErrorAction SilentlyContinue
    if (-not $hfCli) {
        Write-Host "`nhf CLI not found. Install with:" -ForegroundColor Yellow
        Write-Host "  pip install -U huggingface_hub" -ForegroundColor Cyan
        exit 1
    }

    $env:HF_XET_HIGH_PERFORMANCE = "1"
    hf download $Repo $File --local-dir $OutputDir

    if (Test-Path $outFile) {
        $sizeMB = [math]::Round((Get-Item $outFile).Length / 1MB, 0)
        Write-Host "Download complete: $sizeMB MB" -ForegroundColor Green
    } else {
        Write-Host "Download may have failed - file not found at expected path." -ForegroundColor Red
        exit 1
    }
}
