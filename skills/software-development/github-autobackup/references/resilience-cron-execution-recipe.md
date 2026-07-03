# Resilience Cron Execution Recipe (class pattern for sovereign Windows K: backups)

**Trigger**: Data-collection or other prerun script fails with mangled path (code 127: "D:HermesDatascriptsbackup-resilience.sh: No such file or directory"). Report the failure + execute full resilience cycle.

**Core Steps (efficient, autonomous, no-user-present)**:
1. Probe: `ls /d/HermesData/scripts/backup-resilience.sh` and `ls /k/Hermes-Resilience/`
2. Run: `bash /d/HermesData/scripts/backup-resilience.sh` (or direct hermes backup --quick -l "cron-..." + cmd /c robocopy + vault git)
3. Log: Append to `/k/Hermes-Resilience/logs/resilience-cron.log` with:
   ```
   === Resilience Cron Run YYYY-MM-DDTHH:MM:SS ===
   Triggering error (data-collection script failure):
   [exact stderr]
   (Mangled path note.)
   Actions taken:
   - Executed bash ...
   - hermes backup --quick created snapshot ...
   - Robocopy /MIR ... (exit 0)
   - Vault: git ... succeeded (commit SHA)
   - Manifest and logs updated on K:
   - Restore artifacts confirmed: ...
   Backup cycle complete. No new issues. Worst-case restore path supported via K: local mirror + snapshots + git + restore scripts.
   === End run ===
   ```
4. Manifest: Update `/k/Hermes-Resilience/manifests/latest-backup.json` with last_backup TS, quick_zip (or "N/A state-snapshot"), note with verbatim error, snapshot_label, restore_support field.
5. Verify (always): 
   - cat manifest
   - ls /k/Hermes-Resilience/restore/ (restore.sh + .ps1)
   - ls D:/HermesData/state-snapshots/ | tail
   - ls /k/Hermes-Resilience/mirrors/HermesData-Current/ | head
   - tail log
6. Report: Structured summary of trigger + actions + restore confirmation (only because issue present). System delivers. Use [SILENT] only if nothing new.

**hermes --quick note**: Produces state-snapshot (not zip to -o). Mirror includes state-snapshots/.

**Robocopy**: Use script's cmd /c or powershell wrapper; /NFL /NDL etc. for quiet.

**Vault**: Tolerate CRLF warnings; capture commit.

**Restore support (worst-case)**: K: mirror + latest snapshot + git + restore scripts + manifests. One-command restore.ps1/sh preferred.

**Efficiency**: Probes first, full cycle, durable artifacts only, no narration.

Validated 2026-06-27 cycles (multiple times). See evidence.md for raw traces.
