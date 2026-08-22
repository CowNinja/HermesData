# ops/ — two doors, then leaves

Jeff and SAT ask one question: **what is the truth of the stack right now?**

```text
python D:/HermesData/scripts/ops/stack_snapshot_once.py
```

Printable Mermaid (preferred, cache-bypass): http://127.0.0.1:3001/architecture-print.html

CORE heal (only when DOWN):

```text
python D:/HermesData/scripts/ops/speak_and_trust_once.py --status-only
python D:/HermesData/scripts/ops/speak_and_trust_once.py --heal
```

Do not invent a third door. Snapshot never heals. SAT is the only heal door.

Mouths (Discord / WA / Voice) are **pipes**. New public mouth = gateway plugin adapter; do not edit the proxy. Map: Drive `11_Communication_Vectors_and_Modularity.md`.

## Hierarchy

| Role | Script | When |
|------|--------|------|
| **truth** | `stack_snapshot_once.py` | dock/FIFO/hold/engine/pin/shelf + print HTML + live_owner + **watch** (C: free, VRAM leftover, pin age) |
| **heal** | `speak_and_trust_once.py` | CORE ports; `--heal` only when 8642/8091 DOWN |
| kitchen | `../solid_stack_law_once.py` | called by SAT; never freestyle dual-start |
| leaves | `architecture_live_facts_once.py`, `pin_age_once.py`, `model_shelf_status_once.py`, `mermaid_print_html_once.py`, `hub_panel_cache_clear_once.py`, `image_restore_verify_once.py`, `hardware_inventory_once.py`, `self_improve_status_once.py`, `continuity_status_once.py`, `module_missions_once.py`, `verify_once.py` | specialists; snapshot already composes facts/pin/shelf/ingest/print. Hardware, continuity, missions, verify-observe are **leaves** (not auto-run from snapshot). |
| **C: reclaim** | `c_drive_pressure_scout.py` then `c_drive_reclaim_p2a.py` + `c_drive_reclaim_p2b_safe.py` | on-demand when snapshot `C_FREE_LOW`; never a cron |
| **pin write** | `alice_open_loops.py continuity` | Jeff-gated. Measure: `pin_age_once.py` / snapshot watch. Beat-only: `us-now` |
| **leave shelf** | `refresh_free_rankings.py` / `capability_rank.py --status` / `model_shelf_status_once.py` | public grunt only; never Garden |

`scripts/stack_snapshot.py` (no `ops/`) is the **Discord color/thrift** snapshot for solidity_gate. It is not the truth door.

Legacy Phronesis.ps1 shortcuts below are **not** the stack truth door.

## Legacy shortcuts (window launchers)

**Prefer the two doors above.** These map old BAT/PS1 names:

| Old file | Maps to |
|----------|---------|
| `phronesis-start.bat` | `START-PHRONESIS.bat` → `Phronesis.ps1 go` |
| `01-recovery.ps1` | `Phronesis.ps1 restart` |
| `05-stop-all.ps1` | `Phronesis.ps1 stop` |
| `04-status.ps1` | `Phronesis.ps1 status` |
| `Phronesis-Dashboard.ps1` | `Phronesis.ps1 dashboard` |
| `Phronesis-Hygiene-Cycle3.ps1` | `Phronesis.ps1 heal` |
| `Phronesis-Secrets-Git-Autonomy.ps1` | Interactive secrets consolidation + Git backup audit (log: `scripts/ops/secrets-git-log.txt`) |

See `D:\HermesData\scripts\SCRIPTS-MANIFEST.md` for the full guide.
