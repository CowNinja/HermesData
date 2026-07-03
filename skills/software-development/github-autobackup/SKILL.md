---
name: github-autobackup
description: Autonomous background loop for automatic, verifiable GitHub backup after every major action and daily.
version: 1.1
  related_skills: [backup-restore-mechanism, github-integration]
---

# GitHub-AutoBackup (Autonomous Loop) — Sovereign Resilience Backup

**Purpose**: Ensure every meaningful change is automatically backed up with verifiable history. Core DNA: hybrid local-sovereign (K: external 5TB) continuous/incremental mirrors + GitHub for curated Vault/docs + built-in hermes CLI for full state (sessions, DBs, config, skills, memories) + one-command restore playbooks. Supports full replication/restore on new machine.

## Autonomous Loop Configuration
- Trigger: After every major action + daily/hourly via cron (e.g. "Hermes-Resilience-Backup" every 4h) + on-command.
- Actions:
  - Use `hermes backup` / `--quick` for clean state snapshots (handles SQLite via sqlite3.backup(), excludes regenerables like hermes-agent source, venvs, caches, node_modules, .db-wal/shm).
  - Robocopy / mirror selective critical dirs to K:\Hermes-Resilience\mirrors\HermesData-Current (incremental, versioned via dated zips or full mirrors).
  - Vault: real `git commit + push` (PhronesisVault or equivalent private repo) with raw output capture.
  - Maintain phronesis-resilience.md (or equivalent living README) on K: + copy to Vault/Resilience/ + GitHub.
  - Generate manifests, logs, verification evidence.
  - Cron integration for ongoing (script wrappers + direct commands).

## Exact Sovereign Resilience Pattern (from 2026-06-26 high-priority session)
- **K: Structure** (Hermes owns): K:\Hermes-Resilience\ {backups/hermes/ (zips), mirrors/HermesData-Current/, restore/ (restore.ps1 + .sh), scripts/ (backup-resilience.sh), manifests/, logs/, tests/, README.md, phronesis-resilience.md}.
- **Backup frequencies**:
  - Quick/near-continuous: hermes --quick for critical (config, state.db, cron/jobs.json, memories/, auth).
  - Daily/full: hermes backup -o K:\... + robocopy selective mirror (exclude caches, media, large zips, venvs).
  - Vault: git after meaningful changes.
  - Triggers: cron (every 4h+), major checkpoints, on-command.
- **GitHub strategy**: PhronesisVault (curated CNS, plans, resilience md, history). Real pushes with output capture. Large state stays on K: (portable sovereign) or GitHub Releases for small artifacts. Never commit full DBs/caches directly.
- **Restore playbook (worst-case happy path)**: New Windows PC + fresh Hermes + plug K: → run ONE script (`& "K:\Hermes-Resilience\restore\restore.ps1"` or bash equivalent). Script: path probes → hermes import (preferred) or robocopy from mirror → git clone/update Vault → symlink ~/.hermes → verify (status, doctor, state.db size, skills count) → manifest + log.
- **One-time setup / verification**: Path probes (VAULT_CONFIRMED, K: RESILIENCE_CONFIRMED using native D:\ / K:\ ), initial backup + mirror, git push of docs, cron registration, test to temp or spare.
- **Verifiable real actions**: Always execute (git push, write_file, cron create, robocopy, hermes backup) and capture raw terminal output as proof. Embed in logs/manifests.

## Guardrails Enforced
- Non-negotiable core DNA (GitHub-AutoBackup + sovereign K: resilience).
- Verifiable real actions only (no planning-only; capture outputs).
- Extreme simplicity + ruthless pruning ("best part is no part").
- Path discipline: native Windows paths (D:\PhronesisVault, K:\...) for file tools; terminal probes first.
- Maintains clean structure on K: + Vault + GH.
- Supports rollback (git history + dated mirrors/zips) and full restore.
- phronesis-resilience.md as canonical, maintainable playbook (on K: primary, Vault, GitHub).

## Integration
- Works with all other autonomous loops, cron-scheduling, simple-sovereign-work, vault-curation, backup-restore-mechanism.
- Leverages built-in hermes backup/import (preferred for state).
- Provides safety net for "machine gone" scenarios.
- Maintains Vault as authoritative CNS; K: as sovereign execution/silo target.

**Multi-Repo Backup Audit (2026-06-28)**:
When user says "back up to the internet" or "ensure complete recovery", audit ALL working directories — not just the obvious Vault. HermesData (the scripts/configs working dir) may have NO git repo at all.
- **Check every working dir**: `cd <dir> && git remote -v` — if "not a git repository", it needs full setup.
- **New repo creation flow**: `git init` → `gh repo create CowNinja/<Name> --public` → `git remote add origin` → `git fetch` → `git checkout -b main --track origin/main` → selective `git add` → `git commit` → `git push`
- **Selective add is critical**: Don't `git add -A` blindly — MemoryTools/*, lsp/node_modules, agent-tools/*, ComfyUI/, Backups/ all have their own repos or are huge. Add specific subdirs: `git add scripts/ .hermes/ SOUL.md *.md`
- **Lock file gotcha**: If `git add -A` times out on a huge directory, it leaves `.git/index.lock` (0 bytes) that blocks ALL subsequent git operations. A running `git.exe` process (check `tasklist | grep git`) may hold it. Recovery: wait for process to finish, then `rm .git/index.lock`. If stuck: `rm -rf .git && git init` and start fresh from the GitHub remote.
- **Self-recovery watchdog**: Create a cron (every 30m) that checks: (1) gateway reachability, (2) unpushed commits in each repo, (3) K: drive accessibility, (4) auto-pushes if stale. This ensures backups continue even when the primary backup cron fails.

**Git-in-Cron Anti-Patterns (2026-06-29 lesson)**:
Two failure modes when backup scripts do `git add -A` in large working directories:
1. **`git add -A` picks up 100+ untracked files** (WisdomVault/, archives/, bin/, tests/, benchmark files, etc.) → massive commits → slow/failed pushes.
   - **Fix**: Use `git add -u` (tracked files only) + maintain comprehensive `.gitignore` for local-only dirs.
   - **Rule of thumb**: If your `.gitignore` doesn't list every untracked dir pattern, your backup script will bloat.
2. **No timeout on `git push`** → slow push blocks entire cron run → exit 124 timeout.
   - **Fix**: Wrap push in `timeout 45 git push $remote $branch` or a helper function with configurable timeout.
   - **Robocopy mirror exclusions**: Exclude the same dirs from robocopy as from git (.gitignore-as-robocopy-exclude-list pattern).

**Cron job configuration for Windows (hard-won 2026-06-29)**:
- Prefer `no_agent: false` with explicit `bash D:/path/to/script.sh` in prompt over `no_agent: true` with `script:` field — avoids runner path double-prefix bug.
- `workdir` must be Windows absolute path with backslashes: `D:\\HermesData\\scripts`
- `no_agent: true` + `workdir: D:\\X\\scripts` + `script: scripts/foo.sh` → DOUBLE PREFIX → `D:\\X\\scripts\\scripts\\foo.sh` (exit 127).

**Naming Fossils Must Be Scrubbed Thoroughly (2026-06-29)**:
When a project term is deprecated or is a fossil/typo (e.g., "WisdomBolt" → "WisdomVault"):
- Search BOTH trees (HermesData AND PhronesisVault) across ALL relevant extensions: `.py .sh .md .json .yaml .ini .vbs .ps1 .toml .txt .cfg .conf`.
- Check THREE surfaces: (1) source/config files, (2) documentation, (3) on-disk directory names (`mv old new`).
- Do NOT assume a single search catches everything — some references appear in doc comments, some in path strings without trailing slash, some in nested reference files.
- After renaming, run a verification script that checks both the absence of the old term AND the presence of the new term.
- Save the corrected term to persistent memory so future sessions don't recreate the fossil.
- The `.gitignore` and robocopy exclusions in backup-resilience.sh must ALWAYS stay in sync when directory names change.

**Past Lessons Applied**:
- Prevents loss of progress from past weak version control.
- Enforces verifiable real actions.
- Hybrid local (K: mirrors + hermes CLI) + offsite (GitHub) for true resilience.
- One-command restore + copy-paste-ready commands/scripts.
- Session-based, autonomous background via cron.
- 2026-06-26 run: Path mangling in caller scripts (D:HermesDatascripts... without separators) and git-bash /switch mangling for robocopy require explicit probes + powershell wrappers (see references/sovereign-resilience-backup-patterns.md). 'nul' reserved-name git blocks require immediate .bak rename. hermes --quick is snapshot-first. Log cron script failures (127 etc.) to K: manifests/logs while still completing resilience cycle. Background + process tools for long mirrors.

**Real Push / Backup Gate Verification Pattern**:
- Non-negotiable: Execute real operations and capture **raw terminal output** (git push SHA, robocopy stats, hermes backup messages, cron job_id).
- Document in phronesis-resilience.md (or equivalent) + manifests + Vault: exact paths, commands, outputs, timestamps.
- "Repository not found" or partial errors are valid proof — log them.
- Update resilience docs + push before ending session.

**Roemmele/Thompson Influence**:
- Long-term memory preservation through systematic backup.
- Sovereignty through private repo + portable K: external.
- Human-AI symbiosis via clear, executable playbooks.

This skill follows the Research + Verification Mandate and Focused Skill Design principles.

**References**
- references/sovereign-resilience-backup-patterns.md (condensed 2026-06-26 patterns: structure, commands, restore flow, cron example, hermes CLI usage).
- references/autonomous-recovery-repo-pattern.md (dedicated GH recovery repo creation via gh + selective copy + sovereign index update + autonomous "user absent" bootstrap technique from 2026-06-26 session).
- references/2026-06-27-cron-resilience-evidence.md (recurring cron prerun mangled-path 127 handling, hermes --quick snapshot labels, powershell robocopy, large vault git commits, manifest "note" + resilience-cron.log convention, phronesis-resilience.md updates on K:, post-mirror verification commands, restore path confirmation. Fresh 2026-06-27 execution trace extending 2026-06-26 patterns).
- references/resilience-cron-execution-recipe.md (condensed class-level recipe: POSIX probes + bash invocation, structured log append template, manifest format with restore_support, post-run verification commands/checklist, "be efficient + only report if issues + worst-case restore path support" rules; extracted and validated from 2026-06-27 cron resilience cycles).
- Cross-ref simple-sovereign-work (K: ownership, simplicity, verifiable actions, autonomous empowerment), backup-restore-mechanism, vault-curation (resilience.md maintenance), cron-scheduling.
- See `references/multi-repo-github-backup-setup-2026-06-28.md` for the HermesData repo creation, lock file recovery, and multi-repo backup script pattern.

**Dedicated Recovery Repo Pattern (Autonomous Full Setup)**
When user says "do as much as you can autonomously" or "set up a new GitHub repo if you have to":
- Use gh CLI (already authenticated) to create a small dedicated private repo for *lightweight recovery artifacts only* (MDs, restore scripts, wrappers, manifests, evidence).
- Clone, selectively populate (cp only small files; .gitignore for large mirrors/backups), commit/push.
- Update restore scripts + phronesis-resilience.md to advertise the clone URL as source/fallback.
- Autonomously patch sovereign master index (00-MASTER-K-SOVEREIGN-INDEX.md) and generate checksum manifest.
- Sync across K: (primary), Vault/Resilience/, GH.
- Always capture raw outputs; produce durable artifacts (status file, manifest, index section).
- See references/autonomous-recovery-repo-pattern.md for full recipe, pitfalls, and 2026-06-26 execution trace.

**Silo-Progress Resilience Refresh (Five Modified Autonomous Action Items Pattern)**
When user returns after ignoring the resilience thread and reports "I've been working a lot on the data silo":
- Explicitly check "have any of the five autonomous action items changed?"
- Treat the five as *modified* to integrate new silo state (new Personal-Digital-Silo files, Future-Exploration items, tranche proofs, index updates).
- Autonomous actions typically include: (1) selective safe mirror of recent silo artifacts (robocopy only readable/high-signal, handle permission restrictions gracefully), (2) force/harden backup cycle and manifests (use partial when full hits perms), (3) refresh dedicated GH repo + Vault copies with new evidence, (4) update restore scripts/playbook + phronesis-resilience.md with silo cross-refs, (5) generate fresh verification evidence + touch sovereign index.
- Always produce durable artifacts (updated manifest, evidence md in tests/, AUTONOMOUS-STATUS append, index section).
- Capture that the resilience layer must stay synchronized with live silo without blocking silo work.
- See the 2026-06-26 session for the concrete five and execution (partial manifest due to ingest perms, safe mirrors of Goals/Digital-Twin docs + index/proof).

This is the class-level technique for making Hermes tools portable while keeping heavy state on sovereign K:. Integrates with the hybrid backup layers above.
