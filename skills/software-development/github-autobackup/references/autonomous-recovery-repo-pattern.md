# Autonomous Recovery Repo Creation Pattern (2026-06-26)

**Class**: Sovereign Hermes self-resilience setup when user grants full autonomy ("do as much as you can autonomously", "set up a new GitHub repo if you have to").

**Trigger**: Need portable, cloneable recovery tools/scripts/MD separate from heavy state on K: external drive. Main data (state.db, large mirrors) stays sovereign on K:; lightweight artifacts go to dedicated GH repo for easy access on new hardware.

**Core Technique**:
1. `gh repo create Owner/RepoName --private --description "..."` (use gh auth that is already logged in).
2. `git clone https://... /tmp/recovery-repo` (empty repo OK).
3. Selectively copy *only* lightweight items from K:\Hermes-Resilience\ or equivalent:
   - phronesis-resilience.md
   - README.md
   - restore/ (ps1 + sh)
   - scripts/ (wrappers)
   - tests/ (evidence)
   - manifests/ (small json)
   - Never: mirrors/, backups/ (large zips), logs/ with big files.
4. In the clone dir:
   - `cat > .gitignore << 'EOL' ...` (exclude mirrors/, backups/, *.zip, state.db*, etc.).
5. `git add -A && git commit -m "resilience bootstrap: ..." && git push`.
6. Update restore scripts and main MD in place (K: and clone) to reference the new clone URL as source for tools/fallback.
7. Synchronize: cp updated files back to K: primary + Vault/Resilience/.
8. Autonomously patch sovereign index (K:\Phronesis-Sovereign\00-MASTER-K-SOVEREIGN-INDEX.md) via Python append or write with full section describing the package, cron job_id, GH link, recovery path.
9. Generate checksum manifest (Python hashlib.sha256 on key files) and include.
10. Trigger follow-up quick backup + selective mirror.
11. Write AUTONOMOUS-STATUS-*.md log on K:.

**Verification Gate**: Capture full terminal output of gh create, git clone, commit SHA, push, sovereign index append. Update phronesis-resilience.md + manifests with receipts. "Be ACTIVE" — produce durable artifacts.

**Why dedicated repo?** 
- PhronesisVault is for curated CNS (large history, MOCs).
- Heavy state belongs on portable K: (5TB sovereign).
- Small tools/scripts need fast, independent clone on brand-new PC for the "one restore command" happy path.

**Pitfalls Avoided**:
- Committing large files to GH (size limits, cost, clone time).
- Forgetting to update restore scripts with the new source URL.
- Not cross-linking in sovereign master index.
- Using relative/wrong paths (native D:\ K:\ + probes).

**Integration**:
- With github-autobackup and backup-restore-mechanism (this is the "create the tools repo" step in the resilience bootstrap).
- simple-sovereign-work (K: full ownership, verifiable real actions, autonomous empowerment).
- cron-scheduling (register the backup job).
- vault-curation (keep phronesis-resilience.md synced).

**2026-06-26 Execution Receipts** (condensed):
- gh repo create succeeded → https://github.com/CowNinja/Hermes-Resilience
- Selective cp + .gitignore + commit/push (multiple commits: fc50573 initial, later autonomous updates).
- Restore.ps1 updated with "Dedicated GitHub source...".
- Sovereign index appended with "Hermes-Resilience (Autonomous Backup...)" section including job_id, recovery path.
- Checksum manifest + AUTONOMOUS-STATUS file created.
- Synced to K:, Vault, GH.

This pattern makes Hermes "immortal" with minimal user presence.

See main SKILL.md for full sovereign resilience structure and commands. Cross-ref references/sovereign-resilience-backup-patterns.md.