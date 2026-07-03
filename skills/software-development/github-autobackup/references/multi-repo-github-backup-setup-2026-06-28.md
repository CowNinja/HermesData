# Multi-Repo GitHub Backup Setup — 2026-06-28

## Scenario
Jeff's HermesData directory (`D:\HermesData`) had NO git repository — only the Vault was backed up to GitHub. Full internet backup required creating a second repo.

## Repo Created
- **CowNinja/HermesData** — `gh repo create CowNinja/HermesData --public`
- Contains: scripts/, .hermes/config, identity files (SOUL.md, WORKING-DIRECTORY.md)
- Excluded: MemoryTools/* (own repos), lsp/node_modules, agent-tools/*, ComfyUI/, Backups/, caches

## Initial Push Flow (after `git init`)
1. `git remote add origin https://github.com/CowNinja/HermesData.git`
2. `git fetch origin` (gets the empty repo's main branch)
3. `git checkout -b main --track origin/main` (may need to move conflicting .gitignore first)
4. Selective add: `git add scripts/ .hermes/ SOUL.md WORKING-DIRECTORY.md *.md .gitignore`
5. `git commit -m "Initial sovereign workspace backup"`
6. `git push origin main`

## Lock File Recovery
`git add -A` timed out on the huge directory tree, leaving `.git/index.lock` (0 bytes) held by a stuck `git.exe` process (PID 21616). Could not be removed (`Device or resource busy`).

**Workaround**: Cloned the empty GitHub repo to `/tmp/HermesData-backup`, committed .gitignore there, pushed. Then waited for the lock to release, re-init'd the main repo from the remote.

**Prevention**: Never `git add -A` on a directory with 100k+ files. Add specific subdirs.

## Backup Script Updated
`scripts/backup-resilience.sh` now pushes BOTH repos:
- PhronesisVault (existing)
- HermesData (new)

Uses forward-slash paths and `/k/` MSYS path for K: drive detection.
