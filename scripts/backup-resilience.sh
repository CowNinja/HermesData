#!/usr/bin/env bash
# Quick wrapper for resilience backups. Run via cron or manually.
# Usage: bash scripts/backup-resilience.sh (from D:/HermesData)
#
# v2 — selective git operations with timeouts to prevent cron hangs
set -uo pipefail
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
    cmd /c "robocopy \"$HERMES_HOME\" \"$K\\mirrors\\HermesData-Current\" /MIR /FFT /R:1 /W:3 /XD\" \"node_modules\" \"venv\" \".venv\" \"Backups\" \"image_cache\" \"ComfyUI\" \"tmp\" \"cache\" \"audio_cache\" \"bootstrap-cache\" \"WisdomVault\" \"bin\" \"tests\" \"copilot\" \"Revenue\" \"Digital-Twin\" \"analysis\" \"archive\" \"archives\" /XF \"*.zip\" \"*.pyc\" \"*.png\" \"*.jpg\" \"*.tmp\" \"*.log\" /NFL /NDL /NJH /NJS" 2>/dev/null || true
    echo "Robocopy mirror complete"
fi

# Helper: git push with timeout (seconds)
git_push_with_timeout() {
    local dir="$1"
    local remote="$2"
    local branch="$3"
    local timeout_sec="${4:-30}"
    (
        cd "$dir"
        timeout "$timeout_sec" git push "$remote" "$branch" 2>&1 && return 0
        local rc=$?
        if [ $rc -eq 124 ]; then
            echo "WARN: push timed out after ${timeout_sec}s — will retry next cycle"
        else
            echo "WARN: push failed (exit $rc) — will retry next cycle"
        fi
    ) || true
}

# 3) Vault git push (GitHub backup) — selective, only if there are real changes
if [ -d "$HERMES_HOME/../PhronesisVault/.git" ]; then
    (
        cd "$HERMES_HOME/../PhronesisVault"
        # Only commit if there are tracked-file changes (not untracked)
        if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
            git add -u  # only tracked files, not untracked
            git commit -m "auto-resilience backup $TS" 2>/dev/null || true
        fi
        git_push_with_timeout "$HERMES_HOME/../PhronesisVault" origin master 45
    ) || true
    echo "Vault push attempted"
fi

# 4) HermesData self-backup — push scripts/configs to GitHub
if [ -d "$HERMES_HOME/.git" ]; then
    (
        cd "$HERMES_HOME"
        # Only commit tracked-file changes (respects .gitignore)
        if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
            git add -u  # only tracked files
            git commit -m "auto-resilience backup $TS" 2>/dev/null || true
        fi
        git_push_with_timeout "$HERMES_HOME" origin main 45
    ) || true
    echo "HermesData push attempted"
fi

# 5) Update local manifest
if [ -n "$K" ]; then
    mkdir -p "$K/manifests"
    echo "{\"last_backup\":\"$TS\",\"quick_zip\":\"quick-$TS.zip\",\"hermes_home\":\"$HERMES_HOME\"}" > "$K/manifests/latest-backup.json"
fi

echo "=== Backup cycle complete: $TS ==="
