# 2026-07-08 GitHub Repo Sync Cron Audit

**Trigger**: User query on GH profile screenshot showing HermesData (4d), PhronesisVault (4d), Hermes-Resilience (2w), Hermes-Memory-System (3w). "Where is the cron job for GitHub repo syncing?!? Looks unfired for days and weeks!!!"

**Crons involved (live from cronjob list)**:
- Hermes-Resilience-Backup (job_id: 646449c250f1): schedule "every 240m", last_run recent, status ok, script: backup-resilience.py (no_agent, terminal toolset).
- Git-Repo-Recovery-30m (job_id: cc127b21a784): schedule "every 30m", last_run recent, status ok, script: self-recovery-watchdog.py.

**Key scripts**:
- `D:\HermesData\scripts\backup-resilience.py` (v3):
  - ALLOWLIST selective staging for HermesData and PhronesisVault (specific subpaths like scripts/, Operations/, cron/jobs.json, etc.).
  - `git add -u` (tracked only) + allowlist `git add -- <rel>`.
  - Drift report on untracked.
  - Conditional: only `git commit` + `git push origin <branch>` (timeout 45) if status shows changes.
  - Targets: PhronesisVault (master), HermesData (main), PhronesisSilo (K:).
- `D:\HermesData\scripts\backup-resilience.sh`: older wrapper with hermes --quick, robocopy /MIR exclusions, `git_push_with_timeout` helper (45s), conditional `git add -u` + commit + push for Vault and HermesData.
- `D:\HermesData\scripts\self-recovery-watchdog.py`:
  - REPOS list: HermesData/main, PhronesisVault/master, PhronesisSilo/main.
  - `_audit_repo`: rev-list --count origin/... for unpushed, status --porcelain for dirty, remote get-url.
  - If unpushed >0: `_auto_push` (git push, 45s timeout).
  - Dirty only: INFO (normal on dev machine).

**Cron output location**: `D:\HermesData\cron\output/<job_id>/YYYY-MM-DD_HH-MM-SS.md`

**Sample recent output (19:15 resilience)**:
```
## Resilience Backup v3 20260708-191424
## PhronesisVault Backup
OK PhronesisVault: no changes to commit
## HermesData Backup
OK HermesData: no changes to commit
## PhronesisSilo Backup
SKIP PhronesisSilo: directory missing
## Summary
All repos backed up successfully
[OK]
```

**Recovery sample**: unpushed=0 dirty=0 for both; remote= (empty in that run due to git cmd issues in env).

**.git/config verification** (live):
- D:\HermesData: remote origin = https://github.com/CowNinja/HermesData.git ; branch main.
- D:\PhronesisVault: remote origin = https://github.com/CowNinja/PhronesisVault.git ; branch master. (user email/name Hermes).

**Core insight for "unfired" complaints**:
GitHub repo list "Updated X days ago" = last *pushed commit* time. The crons fire on schedule and report [OK], but only produce commits/pushes when tracked changes exist (intentional anti-bloat). Long gaps = stable period, not failure. Other listed repos (Resilience, Memory-System) have no active local git clones or cron targets in this system.

**Verification recipe for future**:
1. `cronjob list` or inspect cron/jobs.json for job names/IDs/schedules/last_run.
2. `ls -lt D:\HermesData\cron/output/<id>/ | head -3` then cat latest log.
3. Read the .py/.sh for current logic.
4. `read_file` on D:\HermesData\.git\config and PhronesisVault one.
5. Cross-check against GH profile timestamps.

**Additional live verification patterns (this session)**:
- Execute the backup script *live* (`python D:\HermesData\scripts\backup-resilience.py`) as primary verification, not just logs.
- Git bypass for shell segfaults/MSYS: Python subprocess with explicit full path `C:\Program Files\Git\cmd\git.exe`, or direct read_file on .git/ files.
- GH list fields: use `primaryLanguage` (not `language`).
- Path fix example: patched script for PhronesisSilo to prefer `K:\Phronesis-Sovereign\Personal-Digital-Silo`.
- Close the loop by updating the living playbook: added "Current Verification (2026-07-08)" section (raw outputs) + "Expanded Replication Plan" (multi-repo targets, layers/frequencies, verification gates, restore enhancements) to `phronesis-resilience.md` on K: and Vault.
- User-requested structure: full verification/probes first, then lay out expanded plan.

**Action taken**: Confirmed remotes, explained conditional logic, located exact crons/scripts/logs. Script patched for Silo. Playbook updated with evidence. No pushes needed (no deltas).

See main SKILL.md for class patterns.