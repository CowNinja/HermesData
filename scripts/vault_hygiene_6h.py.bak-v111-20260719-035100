#!/usr/bin/env python3
"""Vault hygiene every 6h — light, travel-safe, no_agent cron entrypoint.

Research-aligned (BASB CODE + digital-garden automation 2025–26):
  - Automate capture maps / organize / surface; proposal-only for distill merges.
  - Frequent light passes beat rare heavy thrash (SystemSculpt, Obsidian AI gardeners).
  - Keep interpretation + merge/split under Phase B weekly (human-gated waves).

This script (LIGHT only):
  A. refresh_folder_indexes.py  — living CNS 00-INDEX maps (wikilinks)
  B. vaultwalker light dry-run   — PhronesisVault indexes + wall-safe (no deep relocate)
  C. thin scorecard             — Operations/logs/vault-hygiene-6h-latest.md

NOT in this tick (heavier / separate):
  - Phase B merge/split proposals (weekly)
  - Full autonomy suite daily/weekly
  - K: multi-silo deep walk
  - Live VAULTWALKER_LIVE moves

Usage:
  python vault_hygiene_6h.py
  python vault_hygiene_6h.py --timeout 200

Cron: every 6h, no_agent, workdir D:\\HermesData, deliver local.
Exit 0 when core steps ok (soft-fail non-fatal findings).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
VAULT = Path(r"D:\PhronesisVault")
LOG_JSON = HERMES / "logs" / "vault-hygiene-6h-latest.json"
LOG_JSONL = HERMES / "logs" / "vault-hygiene-6h.jsonl"
RECEIPT = VAULT / "Operations" / "logs" / "vault-hygiene-6h-latest.md"


def run_step(name: str, cmd: list[str], timeout: int) -> dict:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(HERMES),
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or ""))[-3000:]
        return {
            "step": name,
            "exit": int(r.returncode),
            "out": out,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as e:
        out = f"TIMEOUT after {timeout}s\n{(e.stdout or '')}\n{(e.stderr or '')}"
        return {"step": name, "exit": 124, "out": out[-3000:], "timeout": True}
    except Exception as e:
        return {
            "step": name,
            "exit": 1,
            "out": f"{type(e).__name__}: {e}",
            "timeout": False,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="6h light vault hygiene (indexes + light walker)")
    ap.add_argument(
        "--timeout",
        type=int,
        default=int(__import__("os").environ.get("VAULT_HYGIENE_6H_TIMEOUT", "200")),
        help="Per-step timeout seconds (stay under Hermes 240s outer cap)",
    )
    args = ap.parse_args()
    py = sys.executable
    ts = datetime.now(timezone.utc).isoformat()
    steps: list[dict] = []

    # A) Index maps (living CNS only — script already skips Roleplay-Sandbox)
    steps.append(
        run_step(
            "refresh_folder_indexes",
            [py, str(SCRIPTS / "refresh_folder_indexes.py")],
            min(args.timeout, 120),
        )
    )

    # B) Light VaultWalker dry-run — second brain only
    steps.append(
        run_step(
            "vaultwalker_light",
            [
                py,
                str(SCRIPTS / "vaultwalker.py"),
                "--silos",
                "PhronesisVault",
                "--cycle",
                "light",
                "--dry-run",
            ],
            min(args.timeout, 150),
        )
    )

    # Soft scoring: index refresh is critical; walker light may soft-fail
    score = 100
    notes: list[str] = []
    risks: list[str] = []
    for s in steps:
        if s["exit"] != 0:
            risks.append(f"{s['step']}:exit_{s['exit']}")
            if s["step"] == "refresh_folder_indexes":
                score -= 40
            else:
                score -= 15
            notes.append(f"{s['step']} exit {s['exit']}")
        else:
            notes.append(f"{s['step']} ok")

    score = max(0, min(100, score))
    # Pipeline green if score >= 70 and indexes ok
    idx_ok = next((s for s in steps if s["step"] == "refresh_folder_indexes"), {}).get("exit", 1) == 0
    pipeline_ok = idx_ok and score >= 70

    payload = {
        "ts": ts,
        "mode": "6h_light",
        "score": score,
        "pipeline_ok": pipeline_ok,
        "notes": notes,
        "risks": risks,
        "steps": [
            {"step": s["step"], "exit": s["exit"], "timeout": s.get("timeout")}
            for s in steps
        ],
        "research_basis": [
            "BASB CODE: Organize + Distill cadence (frequent light organize)",
            "SystemSculpt 2026: automate cleanup/summarize; gate interpretation",
            "X garden-crew 2026: multi-role hygiene + proposal-only writes",
        ],
        "world": "PhronesisVault (world 2)",
        "version": "vault_hygiene_6h/1.0",
    }

    LOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOG_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with LOG_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"""# Vault Hygiene 6h — {ts}

**Score:** {score}/100 · pipeline_ok={pipeline_ok} · mode=light

## Steps
"""
        + "\n".join(f"- `{s['step']}` → exit {s['exit']}" for s in steps)
        + f"""

## Notes
"""
        + "\n".join(f"- {n}" for n in notes)
        + """

## Risks
"""
        + ("\n".join(f"- {r}" for r in risks) if risks else "- none")
        + """

## Cadence
- 6h light: this job (indexes + light walker)
- Daily 04:00: VaultWalker deep dry-run (resurface/review candidates)
- Daily 05:15: Gardener autonomy daily (hubs + wikilink repair)
- Weekly: Phase B proposals + autonomy weekly (merge/split digests)

## Vault links
- [[Operations/Vault-Hygiene-Cadence-CANONICAL-2026-07-12]]
- [[Operations/Vault-Gardener-Automation-System-2026-07-10]]
- [[Operations/Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10]]
""",
        encoding="utf-8",
    )

    # One-liner for cron (empty would be silent; keep short status for audit trail)
    print(f"VaultHygiene6h score={score} ok={pipeline_ok} steps={len(steps)}")
    return 0 if pipeline_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
