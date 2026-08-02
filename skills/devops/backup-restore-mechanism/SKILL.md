---
name: backup-restore-mechanism
description: Backup, restore, and audit trail capabilities with GitHub integration, verification hashes, and rollback procedures.
version: 1.0
  related_skills: [github-autobackup, observability]
---

# Backup/Restore Mechanism Skill — Sovereign Resilience Edition

**Purpose**: Provide reliable backup and restore capabilities with audit trail for full Hermes immortality (state, Vault, sovereign K: mirrors). Concrete implementation: hermes CLI + robocopy mirrors + one-command scripts + GitHub for curated + phronesis-resilience.md playbooks.

## Research-Backed Patterns
- Explicit backup before major changes (hermes --quick + full).
- Clear audit logging + manifests.
- Rollback paths (git + dated mirrors/zips).
- Hybrid local-sovereign (K: 5TB portable) + offsite (GitHub).
- One-command restore for new machine (restore.ps1/.sh).

## Core Functions
- Create timestamped backups via `hermes backup` (full or --quick; clean SQLite snapshots).
- Maintain incremental mirrors with robocopy to K:\Hermes-Resilience\mirrors\...
- Restore from specific backup or mirror (`hermes import` preferred; fallback robocopy).
- List available backups / manifests.
- Generate phronesis-resilience.md style playbooks on K: + Vault + GH.
- Cron integration for continuous (e.g. every 4h resilience job).
- Real-action verification: capture terminal outputs, probes (VAULT_CONFIRMED, K: RESILIENCE_CONFIRMED), post-restore checks (state.db, skills count).

## Sovereign Resilience Structure (class pattern)
K:\Hermes-Resilience\
- backups/hermes/ (zips)
- mirrors/HermesData-Current/
- restore/ (ps1/sh ONE-command scripts)
- scripts/ (wrappers)
- manifests/, logs/, phronesis-resilience.md

See references/sovereign-resilience-backup-patterns.md (in github-autobackup) and references/2026-06-27-cron-resilience-evidence.md for full commands, restore flow, cron example, pitfalls, and 2026-06-27 execution trace.

**2026-06-26 execution hardening (patch)**: 
- Always verify script paths with ls/find before bash calls (mangled "D:HermesDatascripts..." is common in callers).
- Robocopy from git-bash: use `powershell.exe -Command "& 'robocopy' ..."` to avoid /NFL mangling.
- hermes --quick produces state-snapshots/ (label via -l); update manifests conventionally.
- Git 'nul' file: mv to .bak on "failed to insert into database".
- Cron failures: autonomously run resilience + append to K: logs/resilience-cron.log + manifest note. Use background for mirrors. Confirm restore/ + mirrors for worst-case.

**2026-06-27 confirmation (direct application)**: Patterns held exactly during a scheduled cron resilience cycle triggered by recurring data-collection script failure (code 127, mangled path "D:HermesDatascriptsbackup-resilience.sh"). Full autonomous execution: hermes backup --quick (new snapshot 20260627-120217-cron-quick-20260627-080217, ~1.87GB state.db), backup-resilience.sh, robocopy /MIR (exit 0), vault git commit/push (b3517fb), manifest update with verbatim error + "snapshot_label" + detailed "note" + "restore_support", structured append to resilience-cron.log. Explicit post-run verification of restore/ scripts, state-snapshots/, mirrors, logs. No new issues. See github-autobackup references/2026-06-27-cron-resilience-evidence.md for complete trace + refined patterns. Hardening validated; report delivered per cron rules (issues present).

**2026-06-27 12:07 additional re-validation (this cycle)**: Recurring trigger identical. Executed bash /d/HermesData/scripts/backup-resilience.sh (with notify_on_complete for long run). hermes --quick snapshot + robocopy + vault git push succeeded (CRLF warnings tolerated). Manifest updated to 20260627-120723. Appended fresh structured entry to K:/Hermes-Resilience/logs/resilience-cron.log (exact "Triggering error" + "Actions taken:" + "Backup cycle complete. No new issues. Worst-case restore path fully supported" format). Post-run probes confirmed state-snapshots in mirror, restore scripts, healthy K: structure. Followed job rules precisely: efficient, logged to manifests, reported only because of trigger issue (structured failure + recovery + restore confirmation). Patterns 100% stable; no protocol changes. Reconfirms "be efficient, log to K: manifests, only report if issues, support the worst-case restore path" as core for this class. Cross-ref autonomous-execution-protocol (cron discipline) and github-autobackup evidence.md.

## 2026-08-02 v9 cook (K baby + hang fix)

**Research applied**: MS robocopy `/MAX` `/LEV` `/MT` `/R:1`; single-instance locks; soft vs hard phase policy; no full-tree `du` on multi-TB silo.

**Spine**: `scripts/backup-resilience.py` v9 (4h cron) phases:
git HermesData | vault local | k_layout | critical_zip | k_mirror | silo_signal v3 (wall-clock+lock, soft) | vault clean-mirror --if-due | cloud_pack soft | governor | poison_guard | k_inventory soft | fossil_scan soft | manifest_root | phase_policy | health_alarm | restore_drill auto >7d.

**New/updated scripts (token-free)**:
- `backup_k_silo_life_mirror_once.py` v3 — budgeted silo signal; kills hang class (PID 7892)
- `backup_phase_policy.py` — hard/soft classification
- `k_inventory_snapshot.py` — fast K capacity receipt
- `k_fossil_reappearance_scan.py` — giants >5GB live danger
- `backup_health_alarm.py` — soft-aware; healthy silo budget_hit does not YELLOW

**Health target**: GREEN hard=0. Soft never fails receipt alone. K: exclusive Hermes baby (5TB).

**Docs**: `Operations/Backup-Architecture-Cook-2026-08-02-v9.md`, `Operations/Backup-Five-Primaries-Cadence-2026-08-02.md`.

## Future Expansion
- Automated backup scheduling (already via cron-scheduling).
- Remote/encrypted targets.
- Diff visualization.
- Integration with personal-data-silo for K: DT aspects.

**Past Lessons Explicitly Applied**:
- Avoided path pollution (native D:\ K:\ paths, probes first).
- "Best part is no part" applied (leverage built-in hermes backup/import; simple wrappers).
- External research prioritized.
- No premature mutation.
- Verifiable real actions (git pushes, file writes, cron creation with outputs captured).
- Extreme simplicity + copy-paste-ready commands + one-restore-script goal.

**Roemmele/Thompson Influence**:
- Wisdom preservation as foundation of sovereignty.
- Long-term memory + full state via systematic backup.
- Ethical sovereignty guardrails (private GH + portable K: external under Hermes control).

This skill follows the Research + Verification Mandate and Focused Skill Design principles.

**References**:
- Cross-ref github-autobackup (now includes full sovereign resilience patterns + references/sovereign-resilience-backup-patterns.md).
- simple-sovereign-work (K: sovereignty, simplicity, verifiable actions).
- vault-curation (maintain resilience.md in Vault).
