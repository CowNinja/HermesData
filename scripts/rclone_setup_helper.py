#!/usr/bin/env python3
"""
rclone_setup_helper.py - Session 14+
Helps configure and run filtered Medical pulls.
Main working dir: D:\HermesData (C: only for rclone config/temps)

Updated to recommend the new multi-account ingestion orchestrator.
"""

from pathlib import Path
import subprocess

RCLONE = Path("D:/HermesData/rclone_test/rclone.exe")
WORK_DIR = Path("D:/HermesData")

def main():
    print("=== rclone Setup Helper (D:\HermesData primary) ===")
    print("rclone:", RCLONE)
    print("Main data always under:", WORK_DIR)

    print("\n--- Current remotes ---")
    try:
        res = subprocess.run([str(RCLONE), "listremotes"], capture_output=True, text=True, timeout=20)
        print(res.stdout.strip() or "(no remotes configured yet)")
    except Exception as e:
        print("Could not list remotes:", e)

    print("\n--- To set up Google Drive (run once interactively) ---")
    print(str(RCLONE) + " config")
    print("  Name: gdrive  (or old_backup_gdrive, warz_gdrive for multi-account)")
    print("  Type: drive")
    print("  Follow the browser login for the CORRECT Google account per remote.")
    print("  IMPORTANT: Use different remotes + auth with the account that owns the data (see account_clarification).")

    print("\n--- After config, example filtered copy (high-signal Navy/Medical) ---")
    target = WORK_DIR / "data" / "session14_navy_medical"
    print(f"mkdir -p {target}")
    print(f'{RCLONE} copy "gdrive:MemoryCard_Backups/Google Drive/Medical" {target} \\')
    print('    --include "*{DD2807,DD2808,SHPE,VA,Navy,disability,service,separation}*.pdf" \\')
    print("    --progress --transfers 4 --fast-list")

    print("\n--- RECOMMENDED: Use the robust multi-account orchestrator ---")
    print("  It handles multiple remotes/accounts, provenance in every manifest entry,")
    print("  dry-run, and automatically triggers discovery_walker with full source tracking.")
    print(f"  python {WORK_DIR / 'scripts' / 'multi_account_ingest_orchestrator.py'} --dry-run")
    print(f"  python {WORK_DIR / 'scripts' / 'multi_account_ingest_orchestrator.py'} --account old_backup_gdrive")
    print(f"  python {WORK_DIR / 'scripts' / 'multi_account_ingest_orchestrator.py'} --config configs/silo_remotes.example.json")

    print("\n--- Or direct walker with provenance (for single batch) ---")
    print(f"python {WORK_DIR / 'scripts' / 'discovery_walker.py'} {target} 14 50 \\")
    print("  --source-account old_backup_gdrive \\")
    print("  --source-drive-path 'MemoryCard_Backups/Google Drive/Medical' \\")
    print("  --remote-name old_backup_gdrive \\")
    print(f"  --output {WORK_DIR / 'manifests' / 'session14_navy_medical_manifest.json'}")

    print("\nAll main data stays in D:\HermesData. Use --dry-run first if desired.")
    print("See also: multi_account_ingest_orchestrator.py , discovery_walker.py , personal-data-silo skill.")

if __name__ == "__main__":
    main()
