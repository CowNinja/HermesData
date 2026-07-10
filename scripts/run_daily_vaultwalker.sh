#!/usr/bin/env bash
# Daily VaultWalker - SAFE wrapper (dry-run default via vaultwalker_cron.py)
set -e
cd "D:/HermesData" 2>/dev/null || cd /d/HermesData
python "D:/HermesData/scripts/vaultwalker_cron.py" >> "D:/HermesData/logs/daily_vaultwalker.log" 2>&1
echo "=== Safe VaultWalker finished $(date) ===" >> "D:/HermesData/logs/daily_vaultwalker.log"
