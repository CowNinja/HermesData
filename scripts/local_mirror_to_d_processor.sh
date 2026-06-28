#!/usr/bin/env bash
# Autonomous local mirror processor for old Google Drive backups
# Use when rclone auth is not yet available but G: (or K:) mirrors are present.

set -e
MIRROR_BASE="/g/MemoryCard_Backups/Google Drive/Medical"
DEST="/d/HermesData/data/from_local_mirror"
LIST="/d/HermesData/data/session14_pdf_high_signal.txt"

mkdir -p "$DEST"

echo "Copying high-signal PDFs from local G: mirror to D: (D:\HermesData primary)..."
count=0
while read -r f; do
  if [[ -f "$f" ]]; then
    cp -n "$f" "$DEST/" && ((count++)) || true
  fi
  if (( count >= 30 )); then break; fi
done < "$LIST"

echo "Copied $count files."

echo "Now run the walker with provenance:"
echo "python /d/HermesData/scripts/discovery_walker.py $DEST 14 30 \\"
echo "  --source-account old_jeffrey_j_bloom \\"
echo "  --source-original-path 'MemoryCard_Backups/Google Drive/Medical (local mirror)' \\"
echo "  --remote-name local_mirror \\"
echo "  --output /d/HermesData/manifests/sessionXX_local_mirror_manifest.json"
