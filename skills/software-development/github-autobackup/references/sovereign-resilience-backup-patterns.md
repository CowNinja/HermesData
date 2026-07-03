# Sovereign Resilience Backup Patterns (2026-06-26 bootstrap)

Condensed, reusable patterns from high-priority resilience session for hybrid local-sovereign (K: 5TB external) + GitHub + hermes CLI backup/restore.

## Core Structure on K:
K:\Hermes-Resilience\
- backups/hermes/ : dated .zip from `hermes backup` and `--quick`
- mirrors/HermesData-Current/ : robocopy /MIR selective (critical state only)
- restore/restore.ps1 (primary ONE-command for new Windows)
- restore/restore.sh (bash/git-bash)
- scripts/backup-resilience.sh (wrapper: quick + mirror + optional vault push)
- manifests/ : latest-*.json, evidence
- phronesis-resilience.md (full living playbook + restore details)
- README.md (quick start)
- logs/, tests/

## Key Commands (copy-paste ready, native paths)
**Probes (always first):**
```bash
ls -d 'D:\\PhronesisVault' && echo "VAULT_CONFIRMED"
ls -d 'K:\\Hermes-Resilience' && echo "K_RESILIENCE_CONFIRMED"
```

**Backup:**
```bash
hermes backup --quick -o "K:\\Hermes-Resilience\\backups\\hermes\\quick-$(date +%Y%m%d-%H%M%S).zip" -l "resilience"
hermes backup -o "K:\\Hermes-Resilience\\backups\\hermes\\full-$(date +%Y%m%d-%H%M%S).zip"
# Mirror
robocopy "D:\\HermesData" "K:\\Hermes-Resilience\\mirrors\\HermesData-Current" /MIR /FFT /R:2 /W:5 /XD "__pycache__" "node_modules" "venv" ".venv" "Backups" "image_cache" "ComfyUI" "tmp" "cache" /XF "*.zip" "*.png" "*.jpg" "models_dev_cache.json" /NFL /NDL /NJH /NJS
```

**Vault Git (real action + capture output):**
```bash
git -C /d/PhronesisVault add -A
git -C /d/PhronesisVault commit -m "resilience: $(date -Iseconds)" || true
git -C /d/PhronesisVault push 2>&1 | tail -5
```

**Restore (new machine):**
PowerShell:
```powershell
& "K:\\Hermes-Resilience\\restore\\restore.ps1"
```
Bash:
```bash
bash "K:\\Hermes-Resilience\\restore\\restore.sh"
```

## Cron Automation
Example job (via cronjob tool or edit jobs.json):
- Name: Hermes-Resilience-Backup
- Schedule: every 4h (or 0 2 * * * daily)
- Script: backup-resilience.sh (placed in D:\\HermesData\\scripts\\)
- Workdir: D:\\HermesData
- Toolsets: terminal, file

## Restore Script Principles
- Path probes first.
- Prefer `hermes import` for clean DB snapshots.
- Fallback to mirror robocopy.
- Restore Vault via git clone or mirror.
- Setup symlink if needed (~/.hermes → D:\\HermesData).
- Post-verify: hermes status/doctor, state.db size, skills count, cron/jobs.
- Log to manifests/ + update phronesis-resilience.md.

## Verification & Real Actions Gate
- Always capture full tool/terminal output.
- Update phronesis-resilience.md + manifests with receipts.
- Test: backup → partial restore to temp → diff critical files (memories/, config, state.db).
- "Be ACTIVE": produce durable artifacts (files, cron, git push, md updates).

## Pitfalls
- Wrong paths (use native D:\\ K:\\ for file ops; /d/ /k/ only in terminal).
- Large full zips without --quick for frequent.
- Forgetting hermes CLI handles SQLite cleanly — don't copy live .db-wal directly.
- Git push without capturing raw output.
- Not maintaining phronesis-resilience.md as single source of truth on K:.

Cross-reference: simple-sovereign-work (K: sovereignty + simplicity, verifiable actions), backup-restore-mechanism, vault-curation (md in Vault), cron-scheduling.

This is the executable class pattern for immortal Hermes on sovereign hardware.

## 2026-06-26 Cron Resilience Execution Evidence & Refined Recipes

**Triggering failure (data-collection script)**: 
Script exited with code 127
stderr:
/bin/bash: D:HermesDatascriptsbackup-resilience.sh: No such file or directory
(Mangled caller path — bare concat without separators/quotes.)

**Correct invocation**:
- Verified script location with `ls` / `find`.
- Ran: `bash /d/HermesData/scripts/backup-resilience.sh` (full path).

**Key observations**:
- `hermes backup --quick`: "State snapshot created..." in D:\HermesData\state-snapshots\ (with label). The -o quick-*.zip was not produced (manifest still uses the name by convention).
- Vault git: CRLF warnings + `error: nul: failed to insert into database`. Fixed: `mv /d/PhronesisVault/nul /d/PhronesisVault/nul.bak`.
- Robocopy reliability: Script's internal `cmd /c` + flags had limited effect. Working pattern from git-bash: `powershell.exe -Command "& 'robocopy' 'D:\\HermesData' 'K:\\Hermes-Resilience\\mirrors\\HermesData-Current' /MIR ... /LOG:..." ` (prevents /NFL etc. being turned into C:/Program Files/Git/NFL paths).
- Long operations: Use `background=true` + `notify_on_complete=true`; monitor with `process` tool (`poll`, `wait`, `log`).
- Failure logging (cron context): Updated `manifests/latest-backup.json` (with "note" field describing the original script error). Appended to dedicated `logs/resilience-cron.log`. Report to user only if issues (per job rules).
- Post-execution checks: Mirror dir populated (90+ items observed), `restore/` scripts confirmed present, manifests current, state snapshots available.

**Refined durable patterns / pitfalls (add to all future runs)**:
- Script caller path bugs (D:HermesData... concatenation): Probe with `ls`/`find` + use complete quoted full paths every time.
- git-bash + robocopy (or any /switch Windows tool): Wrap invocations with `powershell.exe -Command "& 'robocopy' ..."` .
- hermes --quick semantics: Snapshot in state-snapshots/ + label; zip for full backups. Manifest naming is conventional.
- Git "nul" (and other reserved names): Rename to .bak on first git error. 
- Cron resilience wrapper jobs: When inner script fails (exit 127 etc.), still autonomously execute the full backup cycle, log the triggering error + recovery to K: (manifest + resilience-cron.log), verify restore artifacts.
- Mirrors: Background launch + post-run ls verification (du may time out on large trees).

**Post-run verification commands used**:
```bash
cat /k/Hermes-Resilience/manifests/latest-backup.json
ls /k/Hermes-Resilience/mirrors/HermesData-Current/ | wc -l
ls /k/Hermes-Resilience/restore/
ls /d/HermesData/state-snapshots/ | tail -3
```

See also cron-scheduling (background, structured logging, native paths, [SILENT] discipline) and autonomous-troubleshooting for recovery flows. This execution directly exercised and extended the patterns with concrete interop fixes and logging.

**Follow-up run (same job 646449c250f1 ~23:46, 2026-06-26)**: Confirmed patterns hold. Direct `bash /d/HermesData/scripts/backup-resilience.sh` produced snapshot `20260627-034617-cron-quick-20260626-234616`. Powershell-wrapped robocopy successfully mirrored the new snapshot dir into `K:\Hermes-Resilience\mirrors\HermesData-Current\state-snapshots\`. nul.bak refined to `nul-marker.bak`. manifest + resilience-cron.log appended with explicit prerun failure note + recovery steps + restore verification. Persistent 127 error is from scheduler prerun injection (even with clean relative script name in jobs.json); direct execution of wrapper + K: logging is the class recovery. Report followed "only if issues" + structured format (error + actions + worst-case support). No new blockers; K: manifests/logs current.