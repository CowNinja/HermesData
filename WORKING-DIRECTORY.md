# D:\HermesData — Active Working / System Directory

**Purpose:** All executable code, scripts, data pipelines, ingestion tools, live processing, and system files live here.

**Canonical topology (2026-06-26):** See `D:\PhronesisVault\docs\agent-coordination\Sovereign-Storage-Topology-2026-06-26.md`

| Layer | Path |
|-------|------|
| Runtime (this dir) | `D:\HermesData` |
| Shared brain | `D:\PhronesisVault` |
| Data silo | `K:\Phronesis-Sovereign` (Hermes-managed) |
| Models | `D:\PhronesisModels` |
| Ingest source (read-only) | `G:\MemoryCard_Backups\` |

**Key rules:**
- Run all ingestion, tagging, classification, and automation from this location.
- Use `D:\HermesData\scripts\` for runtime Python (classify_ingest.py, content_extraction_helper.py, discovery_walker.py, crons).
- Operational state: `D:\HermesData\data\` (sync to vault manifests after each tranche).
- Staging: `D:\HermesData\tmp\` relays and batch manifests -> promote receipts to vault.
- Never run live ingest execution from the Obsidian vault (`D:\PhronesisVault\scripts` = router + hygiene only).
- **ASCII-only** executable scripts (`.py` `.ps1` `.cmd` `.bat` `.vbs`); preserve newlines. Policy: `PhronesisVault/Operations/Code-Scripts-ASCII-Policy.md`.

### Connectivity SSOT (2026-08-02) - prevent Discord/WA thrash

| Need | Command / path |
|------|----------------|
| Start/recycle gateway (WhatsApp-safe) | `scripts/Start-HermesGateway-Reliable.ps1` (`-Force` to recycle) |
| Stack board | `python scripts/stack_snapshot.py` |
| Compaction posture | `python scripts/compaction_diagnose.py` |
| Popup/UAC storm | `scripts/ops/Steer-UAC.ps1 -Quiet` / `-Status` |
| Connectivity canon | `PhronesisVault/Operations/Hermes-Connectivity-Discord-WhatsApp-CANONICAL-2026-08-02.md` |
| Popup spawn canon | `PhronesisVault/Operations/Popup-Spawn-Trace-and-Suppress-CANONICAL-2026-08-02.md` |
| Single gateway policy | `PhronesisVault/Operations/SINGLE-GATEWAY-RESTORE.md` |
| Secrets env | `ENV-LOCATION.txt` -> only `D:\HermesData\.env` |

**Never** start gateway with bare schtask pythonw missing `HERMES_HOME` (WhatsApp dies).  
**Never** trust stale `gateway_state.json` alone for WhatsApp.

**Companion location:**  
`D:\PhronesisVault` = Brain / Obsidian vault (plans, canonical manifests, receipts, MOCs).

See also: `D:\PhronesisVault\VAULT-BRAIN.md` · `D:\PhronesisVault\docs\agent-coordination\Grand-Vision-Master-Plan-Addendum-2026-06-26.md`

Session progress is tracked only by session number (not calendar time).

**Post Session 7 note:** Code evaluation performed. Key improvements (modular base_ingest, data-driven tagging rules, file hashing, review tool) now live here.
