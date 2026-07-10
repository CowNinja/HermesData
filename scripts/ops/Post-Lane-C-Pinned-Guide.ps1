# Post + pin Jeff ↔ Grok Direct travel ops guide to Lane C.
$py = "D:\HermesData\hermes-agent\venv\Scripts\python.exe"
$script = "D:\HermesData\scripts\ops\post_lane_c_pin.py"
if (-not (Test-Path $py)) { Write-Error "python venv missing"; exit 1 }
& $py $script
exit $LASTEXITCODE