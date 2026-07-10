#!/usr/bin/env bash
# Daily VaultWalker launcher
# Runs the full silo housekeeping command daily.
# Designed for 30-day autonomous operation while traveling.
# Aligns documents, code, scripts in HermesData, PhronesisVault, K:\Phronesis-Sovereign, Roleplay-Sandbox with Grand Vision.
# Local-first, sub-agent per silo, per-folder indexes, non-ASCII code clean, MD review.

set -e

echo "=== Starting Daily VaultWalker at $(date) ==="

# Navigate to runtime dir (supports git-bash and native)
cd "D:/HermesData" 2>/dev/null || cd /d/HermesData 2>/dev/null || cd "$(dirname "$0")/../.." 

# Execute the VaultWalker command (full 4 silos or subset as needed)
python "D:/HermesData/scripts/vaultwalker.py" --silos HermesData PhronesisVault K_PhronesisSovereign RoleplaySandbox >> "D:/HermesData/logs/daily_vaultwalker.log" 2>&1

echo "=== Daily VaultWalker completed at $(date) ===" >> "D:/HermesData/logs/daily_vaultwalker.log"

# Optional: light touch to confirm
echo "VaultWalker daily run finished successfully." >> "D:/HermesData/logs/daily_vaultwalker.log"
