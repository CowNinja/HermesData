# Seed Alice portrait/style recall hints into Roleplay MEMORY.md from rider log + visual tags.
param(
    [int]$MaxPortraitLines = 5
)

$ErrorActionPreference = "Continue"
$MemoryPath = "D:\PhronesisVault\Roleplay-Sandbox\profile\memories\MEMORY.md"
$RiderLog = "D:\PhronesisVault\Roleplay-Sandbox\runtime\continuity\image-rider.log"
$VisualTags = "D:\PhronesisVault\Roleplay-Sandbox\runtime\visual-tags.yaml"
$Stamp = Get-Date -Format "yyyy-MM-dd HH:mm"

if (-not (Test-Path $MemoryPath)) {
    Write-Host "MEMORY.md missing: $MemoryPath" -ForegroundColor Red
    exit 1
}

$portraits = @()
if (Test-Path $RiderLog) {
    $portraits = Select-String -Path $RiderLog -Pattern "followup channel=.*image=True|portrait" |
        Select-Object -Last $MaxPortraitLines |
        ForEach-Object { $_.Line.Trim() }
}

$aliceHint = ""
if (Test-Path $VisualTags) {
    $vt = Get-Content $VisualTags -Raw
    if ($vt -match 'portrait_prompt:\s*(.+)') {
        $aliceHint = $Matches[1].Trim()
    }
}

$block = @"

---
## Portrait recall seed ($Stamp)
- Canonical: gallery/cast/alice/canonical/portrait.png (832x1216 Pony standard)
- Style anchor: $aliceHint
- Recent rider deliveries:
$(if ($portraits.Count -gt 0) { ($portraits | ForEach-Object { "  - $_" }) -join "`n" } else { "  - (none logged yet)" })
- Preference: elegant library / candlelight / detailed face when user requests dusk portraits
---

"@

Add-Content -Path $MemoryPath -Value $block -Encoding UTF8
Write-Host "WisdomKeeper seed appended to MEMORY.md" -ForegroundColor Green