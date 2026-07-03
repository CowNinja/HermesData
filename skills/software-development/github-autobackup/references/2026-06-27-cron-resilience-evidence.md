# 2026-06-27 Cron Resilience Execution Evidence (recurring data-collection script failure)

**Context**: Recurring scheduled cron job for Hermes-Resilience backup (as cron job with no user present). The "data-collection script" (prerun/invoker) failed with injected/mangled path error (code 127), triggering this resilience cycle per explicit job rules: "Report this to the user." + "Execute the resilience backup" + "Be efficient, log to K: manifests, only report if issues." + "Support the worst-case restore path." + strict delivery ([SILENT] only if genuinely nothing new; otherwise direct report of findings).

Patterns from 2026-06-26 held and were re-exercised successfully.

**Triggering error (exact, recurring)**:
```
Script exited with code 127
stderr:
/bin/bash: D:HermesDatascriptsbackup-resilience.sh: No such file or directory
```
(Mangled caller path — bare concat without separators/quotes in scheduler/prerun. Persistent even with clean relative "backup-resilience.sh" in jobs.json. Scheduler injection bug.)

**Probes (mandatory first step, confirmed)**:
- Script existence: ls /d/HermesData/scripts/backup-resilience.sh → present, executable.
- K: : ls K:/Hermes-Resilience/ → backups/, mirrors/, manifests/, logs/, restore/, scripts/, etc.
- Vault: confirmed for git.
- VAULT_CONFIRMED / K_RESILIENCE_CONFIRMED discipline followed.

**Actions executed (real, with raw output excerpts from 08:02 run)**:
1. `hermes backup --quick` (via script + direct):
   - Output: "State snapshot created: 20260627-120217-cron-quick-20260627-080217
  18 snapshot(s) stored in D:\HermesData/state-snapshots/
  Restore with: /snapshot restore 20260627-120217-cron-quick-20260627-080217"
   - Note: --quick = state-snapshots/ (large state.db ~1.87GB) + label via -l. No actual quick-*.zip in this invocation; manifest uses "N/A (state-snapshot via --quick)".

2. Direct script execution (correct full path):
   - `bash /d/HermesData/scripts/backup-resilience.sh`
   - Output excerpt:
     ```
     === Resilience Backup 20260627-080217 ===
     State snapshot created: 20260627-120217-cron-quick-20260627-080217
     warning: in the working copy of ... CRLF will be replaced by LF ...
     [master b3517fb] auto-resilience backup 20260627-080217
     15 files changed, 1626 insertions(+), 498 deletions(-)
     To https://github.com/CowNinja/PhronesisVault.git
     b42ab50..b3517fb  master -> master
     Backup cycle complete. Logged to K: manifests + logs.
     ```

3. Robocopy selective mirror:
   - Script internal: `cmd /c "robocopy \"D:\\HermesData\" \"K:\\Hermes-Resilience\\mirrors\\HermesData-Current\" /MIR ... /NFL /NDL /NJH /NJS" || true`
   - Explicit follow-up: same with /LOG to K: logs.
   - Result: exit 0. Recent logs in K:/Hermes-Resilience/logs/ are small (2 bytes for no-net-change runs). Mirror dir current (~123 items observed).

4. Vault git push:
   - Performed inside script (cd /d/PhronesisVault; git add -A; commit -m "..."; push).
   - Success with CRLF warnings tolerated; new commit b3517fb captured.

5. K: logging & manifests (durable artifacts):
   - Updated `manifests/latest-backup.json`:
     ```json
     {
       "last_backup": "20260627-080217",
       "quick_zip": "N/A (state-snapshot via --quick)",
       "snapshot_label": "20260627-120217-cron-quick-20260627-080217",
       "note": "Data-collection script failure (original trigger): Script exited with code 127\nstderr:\n/bin/bash: D:HermesDatascriptsbackup-resilience.sh: No such file or directory\n(Mangled path in caller/scheduler). Paths probed and verified (VAULT_CONFIRMED, K_RESILIENCE_CONFIRMED, script found at /d/HermesData/scripts/backup-resilience.sh). hermes backup --quick + backup-resilience.sh run + vault git push + robocopy /MIR executed successfully. New snapshot created. Restore artifacts (restore.ps1/sh, mirrors/HermesData-Current, manifests, state-snapshots) confirmed present for worst-case. No blocking issues for backup layer. K: manifests/logs updated. Mirror and vault current.",
       "timestamp": "20260627-080217",
       "restore_support": "hermes snapshot restore preferred (see state-snapshots/), or robocopy from K:/Hermes-Resilience/mirrors/HermesData-Current + git for Vault + full backups in K:/Hermes-Resilience/backups/"
     }
     ```
   - Appended `logs/resilience-cron.log` with full structured entry:
     ```
     === Resilience Cron Run 2026-06-27T08:05:24-04:00 ===
     Triggering error (data-collection script failure):
     Script exited with code 127
     stderr:
     /bin/bash: D:HermesDatascriptsbackup-resilience.sh: No such file or directory
     (Mangled path in caller/scheduler. Paths probed and verified.)
     Actions taken:
     - Executed bash /d/HermesData/scripts/backup-resilience.sh (TS 20260627-080217)
     - hermes backup --quick created snapshot 20260627-120217-cron-quick-20260627-080217 (state-snapshot, ~1.87GB incl state.db)
     - Robocopy /MIR selective to K:/Hermes-Resilience/mirrors/HermesData-Current executed (exit 0)
     - Vault: git add/commit/push succeeded (commit b3517fb)
     - Manifest and logs updated on K:
     - Restore artifacts confirmed: restore.sh/ps1, state-snapshots, mirrors, full zips if present.
     Backup cycle complete. No new blocking issues for resilience layer. Worst-case restore path supported.
     === End run 20260627-080524 ===
     ```

6. Restore path verification (worst-case support, explicit):
   - `ls K:/Hermes-Resilience/restore/` → restore.ps1, restore.sh (and backup-resilience.sh copied).
   - `ls D:/HermesData/state-snapshots/ | tail -5` → ...20260627-120217-cron-quick-20260627-080217 present with state.db (~1.87GB), manifest.json, etc.
   - Mirror structure healthy.
   - No issues.

**Refined / confirmed class patterns & pitfalls (add to all future resilience cycles)**:
- **Mangled path handling (recurring scheduler artifact)**: Probe existence first with ls/find using full /d/ or D:\ paths. Always invoke with complete `bash /d/HermesData/scripts/backup-resilience.sh`. Log the *exact original stderr* verbatim into both manifest "note" and resilience-cron.log. Proceed autonomously with full cycle anyway.
- **hermes --quick semantics**: State snapshot (with label) in D:/HermesData/state-snapshots/; manifest "quick_zip": "N/A (state-snapshot via --quick)"; "snapshot_label" field.
- **Robocopy in git-bash**: Internal script `cmd /c` works but may suppress logs. Explicit run or powershell wrapper for /LOG. Small/empty logs on no-net-change are normal (still success).
- **Manifest convention**: Include original error verbatim, snapshot_label, explicit "restore_support" field, "No new blocking issues", "K: manifests/logs updated".
- **Vault git**: CRLF warnings expected (tolerate); capture commit SHA and push range. Large or small commits both success. "up-to-date" is fine.
- **Logging discipline (cron context)**: Use dedicated resilience-cron.log with === headers, "Triggering error", "Actions taken:" bullets, "Backup cycle complete." Close with restore confirmation. Matches autonomous-execution + cron-scheduling rules.
- **Report rules**: Per job: "only report if issues" + explicit "Report this to the user" for the data-collection failure. Produce structured direct report (error + actions + verification) since failure present. Never [SILENT] when there is a triggering error to surface. Final output is the report (system delivers automatically).
- **Verification discipline (always post-run)**: Confirm state-snapshots/ latest, restore/ scripts, manifest content, log tail, mirror items. Snapshot dir probe (ls .../state-snapshots/ | tail).
- **No new blockers**: Treat recurring 127 as known scheduler quirk; resilience layer absorbs via direct execution + durable K: artifacts.
- **Restore happy path supported**: K: structure (restore scripts + current mirror + latest snapshot + git HEAD + manifests) is the proof. hermes snapshot restore or robocopy + git.

**Post-run verification commands used (this execution)**:
```bash
cat K:/Hermes-Resilience/manifests/latest-backup.json
ls -lt K:/Hermes-Resilience/logs/ | head -3
ls D:/HermesData/state-snapshots/ | tail -3
ls K:/Hermes-Resilience/restore/
ls K:/Hermes-Resilience/mirrors/HermesData-Current/ | head -5
tail -20 K:/Hermes-Resilience/logs/resilience-cron.log
```

**Cross-refs**: 
- github-autobackup main SKILL.md and sovereign-resilience-backup-patterns.md (2026-06-26 baseline + prior follow-ups).
- backup-restore-mechanism (hardening notes; this is direct application).
- cron-scheduling (delivery rules, [SILENT] vs report, structured cron entries, workdir/path discipline, no-user-present execution).
- autonomous-execution-protocol (cron job rules, silent vs surface only on issues/blockers, traceability via logs/manifests/git).
- autonomous-troubleshooting (graceful absorption of known scheduler error).
- structured-logging-resilience (rich structured appends with context).

This trace demonstrates the class-level recovery: log the failure exactly, execute the full resilience backup autonomously (script + equivalents), produce durable K: manifests/logs/artifacts, explicitly confirm worst-case restore support. Patterns stable and reinforced. No changes to core procedure needed.

*Evidence captured / extended 2026-06-27 (08:02 cycle). Ready for next recurrence, restore test, or skill distillation.*

**Prior runs referenced in this file (for completeness)**: Earlier 03:57 cycle with similar structure (different snapshot labels like 20260627-075703-...); patterns identical. This 08:02 run added fresh snapshot 20260627-120217-..., explicit robocopy verification, larger log append, updated manifest with expanded "note" and "restore_support".
