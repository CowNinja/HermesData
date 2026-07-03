#!/usr/bin/env bash
# prepare_rclone_medical.sh
# Session 14+ helper - safe rclone setup and filtered Medical pull
# Always targets D:\HermesData for main working data (C: only for temps/config if needed)
#
# NOTE: For multi-account use the Python orchestrator:
#   python D:/HermesData/scripts/multi_account_ingest_orchestrator.py ...

set -e

RCLONE_BIN="/d/HermesData/rclone_test/rclone.exe"
WORK_DIR="/d/HermesData"
DATA_DIR="$WORK_DIR/data"
MANIFEST_DIR="$WORK_DIR/manifests"
SLICE_LIST="$WORK_DIR/medical_remaining_slice.txt"

echo "=== rclone Medical Pull Prep (D:\HermesData primary) ==="
echo "rclone binary: $RCLONE_BIN"
echo "Working data always under: $WORK_DIR"

# 1. Ensure config (user may need to run this interactively once)
echo ""
echo "Step 1: Configure Google Drive remote (if not done)"
echo "Run this manually if needed:"
echo "  $RCLONE_BIN config"
echo "Recommended remote name: gdrive (or separate old_backup_gdrive / warz_gdrive)"
echo "Use 'drive' type, follow browser auth for the account that owns the target path."
echo "Config file will land in C:\\Users\\... (acceptable for temp/config per your note)"

# 2. Example high-signal filtered copy (use after config)
echo ""
echo "Step 2: After config, copy a filtered high-signal slice"
echo "Example (50 files max, Navy/VA/SHPE/DD keyword files):"
echo "  mkdir -p $DATA_DIR/session14_navy_medical"
echo "  $RCLONE_BIN copy \"gdrive:MemoryCard_Backups/Google Drive/Medical\" \\"
echo "    $DATA_DIR/session14_navy_medical \\"
echo "    --include \"*{DD2807,DD2808,SHPE,VA,Navy,disability,service,separation}*.{pdf,txt,docx}\" \\"
echo "    --max-transfer 2G --progress --transfers 4 --fast-list"

# 3. After copy, prefer orchestrator or run walker
echo ""
echo "Step 3: PREFERRED - use multi-account orchestrator (auto provenance + walker trigger)"
echo "  python $WORK_DIR/scripts/multi_account_ingest_orchestrator.py --dry-run"
echo "  python $WORK_DIR/scripts/multi_account_ingest_orchestrator.py --account old_backup_gdrive"

echo "  # Or walker directly with provenance flags:"
echo "  python $WORK_DIR/scripts/discovery_walker.py \\"
echo "    $DATA_DIR/session14_navy_medical 14 50 \\"
echo "    --source-account old_backup_gdrive --source-drive-path 'MemoryCard_Backups/Google Drive/Medical' \\"
echo "    --remote-name gdrive --output $MANIFEST_DIR/session14_navy_medical_manifest.json"

# 4. Safety notes
echo ""
echo "Safety:"
echo "- All main data -> D:\HermesData"
echo "- Use --dry-run first"
echo "- rclone crypt recommended for medical data at rest"
echo "- Check disk before large pulls (C: ~14GB free is ok for temps)"

echo ""
echo "Ready when you run the config + copy commands."
echo ""
echo "=== Quick filtered high-signal list ready ==="
echo "D:/HermesData/data/session14_high_signal_list.txt (logic prepared from 150-line slice)"
echo "Target remote path: gdrive:MemoryCard_Backups/Google Drive/Medical"
echo "Recommended first pull size: 30-50 files"
