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
- Staging: `D:\HermesData\tmp\` relays and batch manifests → promote receipts to vault.
- Never run live ingest execution from the Obsidian vault (`D:\PhronesisVault\scripts` = router + hygiene only).

**Companion location:**  
`D:\PhronesisVault` = Brain / Obsidian vault (plans, canonical manifests, receipts, MOCs).

See also: `D:\PhronesisVault\VAULT-BRAIN.md` · `D:\PhronesisVault\docs\agent-coordination\Grand-Vision-Master-Plan-Addendum-2026-06-26.md`

Session progress is tracked only by session number (not calendar time).

**Post Session 7 note:** Code evaluation performed. Key improvements (modular base_ingest, data-driven tagging rules, file hashing, review tool) now live here.
