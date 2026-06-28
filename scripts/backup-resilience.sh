#!/usr/bin/env bash
# Quick wrapper for resilience backups. Run via cron or manually.
# Usage: bash scripts/backup-resilience.sh (from D:/HermesData)
set -euo pipefail
TS=$(date +%Y%m%d-%H%M%S)
HERMES_HOME="$(cd "$(dirname "$0")/.." && pwd)"

# Resolve K: drive — try /k/ (MSYS) first, fall back to native
if [ -d "/k/Hermes-Resilience" ]; then
    K="/k/Hermes-Resilience"
elif [ -d "K:/Hermes-Resilience" ]; then
    K="K:/Hermes-Resilience"
else
    echo "K: drive not accessible — skipping local backup"
    K=""
fi

echo "=== Resilience Backup $TS ==="
echo "HERMES_HOME=$HERMES_HOME"
echo "K=$K"

# 1) Hermes quick backup (zip of config/state)
if [ -n "$K" ]; then
    hermes backup --quick -o "$K/backups/hermes/quick-$TS.zip" -l "cron-quick-$TS" 2>/dev/null || echo "NOTE: hermes quick backup skipped"
fi

# 2) Robocopy mirror to K: (only if available)
if [ -n "$K" ]; then
    cmd /c "robocopy \"$HERMES_HOME\" \"$K\\mirrors\\HermesData-Current\" /MIR /FFT /R:1 /W:3 /XD__\" \"node_modules\" \"venv\" \".venv\" \"Backups\" \"image_cache\" \"ComfyUI\" \"tmp\" \"cache\" /XF \"*.zip\" \"*.pyc\" \"*.png\" \"*.jpg\" /NFL /NDL /NJH /NJS" 2>/dev/null || true
    echo "Robocopy mirror complete"
fi

# 3) Vault git push (GitHub backup)
if [ -d "$HERMES_HOME/../PhronesisVault/.git" ]; then
    (
        cd "$HERMES_HOME/../PhronesisVault"
        git add -A
        git commit -m "auto-resilience backup $TS" || true
        git push 2>&1 || echo "WARN: vault push failed — will retry next cycle"
    ) || true
    echo "Vault push attempted"
fi

# 4) HermesData self-backup — push scripts/configs to GitHub
if [ -d "$HERMES_HOME/.git" ]; then
    (
        cd "$HERMES_HOME"
        git add -A
        git commit -m "auto-resilience backup $TS" || true
        git push 2>&1 || echo "WARN: HermesData push failed — remote may not be configured"
    ) || true
    echo "HermesData push attempted"
fi

# 5) Update local manifest
if [ -n "$K" ]; then
    mkdir -p "$K/manifests"
    echo "{\"last_backup\":\"$TS\",\"quick_zip\":\"quick-$TS.zip\",\"hermes_home\":\"$HERMES_HOME\"}" > "$K/manifests/latest-backup.json"
fi

echo "=== Backup cycle complete: $TS ==="
