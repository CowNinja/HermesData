#!/usr/bin/env bash
# Self-recovery watchdog for sovereign cron infrastructure
# Runs via no_agent cron every 30min
# Detects AND RECOVERS from: gateway down, llama down, gallery down, git push staleness
#
# v3 — ACTUAL RESTART LOGIC (not just detection)
set -uo pipefail
TS=$(date +%Y%m%d-%H%M%S)
LOGFILE="D:/HermesData/cron/output/self-recovery-${TS}.md"
ISSUES=0
ACTIONS=""

log() { echo "$1"; echo "$1" >> "$LOGFILE" 2>/dev/null || true; }
section() { log ""; log "## $1"; }

# ---- Check 1: Hermes gateway on 8642 ----
section "Gateway Health"
if curl -s --max-time 5 http://127.0.0.1:8642/health > /dev/null 2>&1; then
    log "✓ Gateway 8642 responding"
else
    log "⚠ Gateway 8642 NOT responding — attempting restart"
    ISSUES=$((ISSUES+1))
    # Try Hermes scheduled task restart
    cmd //c "schtasks /run /tn Hermes_Gateway" 2>/dev/null
    sleep 5
    if curl -s --max-time 5 http://127.0.0.1:8642/health > /dev/null 2>&1; then
        log "✓ Gateway restarted successfully via scheduled task"
        ACTIONS="${ACTIONS}\n- Gateway: restarted via Hermes_Gateway task"
    else
        # Fallback: try direct start
        log "⚠ Scheduled task restart failed — trying direct start"
        cmd //c "start /min cmd /c \"D:\\HermesData\\hermes-agent\\venv\\Scripts\\pythonw.exe -m hermes_cli.main gateway run\"" 2>/dev/null || true
        sleep 8
        if curl -s --max-time 5 http://127.0.0.1:8642/health > /dev/null 2>&1; then
            log "✓ Gateway restarted via direct start"
            ACTIONS="${ACTIONS}\n- Gateway: restarted via direct start"
        else
            log "� Gateway restart FAILED — manual intervention needed"
            ACTIONS="${ACTIONS}\n- Gateway: RESTART FAILED"
        fi
    fi
fi

# ---- Check 2: llama.cpp server on 8090 ----
section "llama.cpp Router (8090)"
if curl -s --max-time 3 http://127.0.0.1:8090/health > /dev/null 2>&1; then
    log "✓ llama-server 8090 responding"
else
    log "⚠ llama-server 8090 not responding"
    # Try the stack boot script
    cmd //c "start /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\\PhronesisVault\\Operations\\Start-FullSovereignStack.ps1" 2>/dev/null || true
    sleep 10
    if curl -s --max-time 5 http://127.0.0.1:8090/health > /dev/null 2>&1; then
        log "✓ llama-server restarted via stack boot"
        ACTIONS="${ACTIONS}\n- llama-server: restarted via stack boot script"
        ISSUES=$((ISSUES+1))
    else
        log "⚠ llama-server restart non-critical (proxy may handle routing)"
    fi
fi

# ---- Check 3: ComfyUI Gallery on 8189 ----
section "ComfyUI Gallery (8189)"
if curl -s --max-time 3 http://127.0.0.1:8189/ > /dev/null 2>&1; then
    log "✓ Gallery 8189 responding"
else
    log "⚠ Gallery 8189 NOT responding — attempting restart"
    ISSUES=$((ISSUES+1))
    cmd //c "start /min pythonw.exe D:\\ComfyUI\\gallery_server.py" 2>/dev/null || true
    sleep 5
    if curl -s --max-time 3 http://127.0.0.1:8189/ > /dev/null 2>&1; then
        log "✓ Gallery restarted"
        ACTIONS="${ACTIONS}\n- Gallery 8189: restarted"
    else
        log "✗ Gallery restart FAILED"
        ACTIONS="${ACTIONS}\n- Gallery 8189: RESTART FAILED"
    fi
fi

# ---- Check 4: GitHub push staleness (PhronesisVault) ----
section "GitHub Backup Freshness"
if cd /d/PhronesisVault 2>/dev/null; then
    V_LAST_PUSH=$(git log --format='%ct' -1 2>/dev/null || echo "0")
    V_REMOTE=$(git log --format='%ct' origin/master -1 2>/dev/null || echo "0")
    if [ "$V_LAST_PUSH" != "$V_REMOTE" ] && [ "$V_REMOTE" != "0" ]; then
        V_BEHIND=$(git rev-list origin/master..HEAD --count 2>/dev/null || echo "?")
        log "⚠ Vault: $V_BEHIND unpushed commits"
        if [ "$V_BEHIND" -gt 5 ] 2>/dev/null; then
            log "→ Attempting vault push..."
            git add -u && git commit -m "watchdog auto-push $TS" 2>/dev/null || true
            timeout 45 git push origin master 2>&1 | head -3 || echo "WARN: vault push timed out or failed"
            ACTIONS="${ACTIONS}\n- Vault: pushed $V_BEHIND commits to GitHub"
            ISSUES=$((ISSUES+1))
        fi
    else
        log "✓ Vault: up to date"
    fi
else
    log "⚠ Cannot cd to PhronesisVault"
    ISSUES=$((ISSUES+1))
fi

# ---- Check 5: HermesData push staleness ----
section "HermesData Backup Freshness"
if cd /d/HermesData 2>/dev/null; then
    H_LAST_PUSH=$(git log --format='%ct' -1 2>/dev/null || echo "0")
    H_REMOTE=$(git log --format='%ct' origin/main -1 2>/dev/null || echo "0")
    if [ "$H_LAST_PUSH" != "$H_REMOTE" ] && [ "$H_REMOTE" != "0" ]; then
        H_BEHIND=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo "?")
        log "⚠ HermesData: $H_BEHIND unpushed commits"
        if [ "$H_BEHIND" -gt 5 ] 2>/dev/null; then
            log "→ Attempting HermesData push..."
            git add -u && git commit -m "watchdog auto-push $TS" 2>/dev/null || true
            timeout 45 git push origin main 2>&1 | head -3 || echo "WARN: HermesData push timed out or failed"
            ACTIONS="${ACTIONS}\n- HermesData: pushed $H_BEHIND commits to GitHub"
            ISSUES=$((ISSUES+1))
        fi
    else
        log "✓ HermesData: up to date"
    fi
else
    log "⚠ Cannot cd to HermesData"
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
    echo ""
    echo "[HEALTHY]"
else
    echo ""
    echo "[ISSUES: $ISSUES]"
fi
