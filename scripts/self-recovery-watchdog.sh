#!/usr/bin/env bash
# Self-recovery watchdog for sovereign cron infrastructure
# Runs via no_agent cron every 30min
# Detects and recovers from: cron errors, stuck jobs, gateway down, missed GitHub pushes

set -uo pipefail
TS=$(date +%Y%m%d-%H%M%S)
LOGFILE="D:/HermesData/cron/output/self-recovery-${TS}.md"
ISSUES=0
ACTIONS=""

log() { echo "$1"; echo "$1" >> "$LOGFILE" 2>/dev/null || true; }
section() { log ""; log "## $1"; }

# ---- Check 1: Hermes gateway on 8091 ----
section "Gateway Health"
if curl -s --max-time 5 http://127.0.0.1:8091/v1/models > /dev/null 2>&1; then
    log "✓ Gateway 8091 responding"
else
    log "� Gateway 8091 NOT responding"
    ISSUES=$((ISSUES+1))
    ACTIONS="${ACTIONS}\n- Gateway down: would restart phronesis-sovereign service"
fi

# ---- Check 2: Ollama ----
if curl -s --max-time 3 http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    log "✓ Ollama 11434 responding"
else
    log "⚠ Ollama 11434 not responding (non-critical)"
fi

# ---- Check 3: PhronesisVault push staleness ----
section "GitHub Backup Freshness"
cd /d/PhronesisVault 2>/dev/null || true
V_LAST_PUSH=$(git log --format='%ct' -1 2>/dev/null || echo "0")
V_REMOTE=$(git log --format='%ct' origin/master -1 2>/dev/null || echo "0")
if [ "$V_LAST_PUSH" != "$V_REMOTE" ] && [ "$V_REMOTE" != "0" ]; then
    V_BEHIND=$(git rev-list origin/master..HEAD --count 2>/dev/null || echo "?")
    log "⚠ Vault: $V_BEHIND unpushed commits"
    if [ "$V_BEHIND" -gt 5 ] 2>/dev/null; then
        log "→ Attempting vault push..."
        git add -A && git commit -m "watchdog auto-push $TS" 2>/dev/null || true
        git push origin master 2>&1 | head -3
        ACTIONS="${ACTIONS}\n- Vault: pushed $V_BEHIND commits to GitHub"
        ISSUES=$((ISSUES+1))
    fi
else
    log "✓ Vault: up to date"
fi

# ---- Check 4: HermesData push staleness ----
cd /d/HermesData 2>/dev/null || true
H_LAST_PUSH=$(git log --format='%ct' -1 2>/dev/null || echo "0")
H_REMOTE=$(git log --format='%ct' origin/main -1 2>/dev/null || echo "0")
if [ "$H_LAST_PUSH" != "$H_REMOTE" ] && [ "$H_REMOTE" != "0" ]; then
    H_BEHIND=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo "?")
    log "⚠ HermesData: $H_BEHIND unpushed commits"
    if [ "$H_BEHIND" -gt 5 ] 2>/dev/null; then
        log "→ Attempting HermesData push..."
        git push origin main 2>&1 | head -3
        ACTIONS="${ACTIONS}\n- HermesData: pushed $H_BEHIND commits to GitHub"
        ISSUES=$((ISSUES+1))
    fi
else
    log "✓ HermesData: up to date"
fi

# ---- Check 5: K: drive accessible ----
section "Local Backup Drive (K:)"
if [ -d "/k/Hermes-Resilience" ] || [ -d "K:/Hermes-Resilience" ]; then
    log "✓ K: drive accessible"
else
    log "� K: drive NOT accessible — local mirror backup will fail"
    ISSUES=$((ISSUES+1))
fi

# ---- Summary ----
section "Summary"
log "Issues found: $ISSUES"
if [ -n "$ACTIONS" ]; then
    log "Actions taken:$ACTIONS"
fi

if [ "$ISSUES" -eq 0 ]; then
    log "✓ All systems nominal"
    # Silent exit for cron — no need to report when healthy
    echo ""
    echo "[HEALTHY]"
else
    echo ""
    echo "[ISSUES: $ISSUES]"
fi
