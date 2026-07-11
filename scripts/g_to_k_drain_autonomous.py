#!/usr/bin/env python3
"""Autonomous G→K wave runner for no_agent cron.

- Sources: MemoryCard historical Google Drive only (not live D: My Drive)
- Copy-only with provenance via g_to_k_safe_drain.py
- Bounded inbox re-home + entity mine each tick
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-autonomous-wave-latest.md")
LIMIT = 120


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    lines = [f"# G→K autonomous wave — {ts}", ""]

    code_h, out_h = run([sys.executable, str(SCRIPTS / "pipeline_health_check.py")], 120)
    lines.append(f"## Health exit={code_h}")
    lines.append("```"); lines.append(out_h[-600:]); lines.append("```")
    code, out = run([sys.executable, str(SCRIPTS / "g_memorycard_inventory.py")], 180)
    lines.append(f"## Inventory exit={code}")
    lines.append("```")
    lines.append(out[-1200:])
    lines.append("```")

    run(
        [
            sys.executable,
            str(SCRIPTS / "lifecycle_index.py"),
            "inventory",
            "--root",
            r"G:\MemoryCard_Backups\Google Drive",
            "--limit",
            "150",
        ],
        300,
    )
    run([sys.executable, str(SCRIPTS / "lifecycle_index.py"), "queue", "--limit", "80"], 60)

    code2, out2 = run(
        [
            sys.executable,
            str(SCRIPTS / "g_to_k_safe_drain.py"),
            "--apply", "--ai-inbox", "--ai-inbox-cap", "10",
            "--limit",
            str(LIMIT),
            "--source",
            r"G:\MemoryCard_Backups\Google Drive",
            "--source",
            r"G:\MemoryCard_Backups\Google Drive(archive)",
        ],
        900,
    )
    lines.append(f"## Drain apply exit={code2}")
    lines.append("```")
    lines.append(out2[-1500:])
    lines.append("```")

    code3, out3 = run(
        [sys.executable, str(SCRIPTS / "k_inbox_rehome.py"), "--apply", "--limit", "40"],
        300,
    )
    lines.append(f"## Inbox rehome exit={code3}")
    lines.append("```")
    lines.append(out3[-800:])
    lines.append("```")

    code4, out4 = run(
        [sys.executable, str(SCRIPTS / "entity_mine.py"), "--limit", "5000"],
        300,
    )
    lines.append(f"## Entity mine exit={code4}")
    lines.append("```")
    lines.append(out4[-600:])
    lines.append("```")

    run([sys.executable, str(SCRIPTS / "ingest_registry.py"), "stats"], 60)
    run([sys.executable, str(SCRIPTS / "batch_train_derivatives.py"), "--limit", "15"], 300)
    run([sys.executable, str(SCRIPTS / "registry_fixity_batch.py"), "--limit", "50"], 600)
    run([sys.executable, str(SCRIPTS / "dlq_retry.py"), "--limit", "10"], 300)
    run([sys.executable, str(SCRIPTS / "coverage_reconcile.py"), "--max-scan", "20000"], 600)

    # Foundation layers: context detective, process_status, batch enrich
    run([sys.executable, str(SCRIPTS / "file_context_enrich.py"), "--limit", "15"], 180)
    run([sys.executable, str(SCRIPTS / "process_status_batch.py"), "--limit", "200"], 120)
    run([sys.executable, str(SCRIPTS / "batch_context_enrich.py"), "--limit", "30"], 180)
    run([sys.executable, str(SCRIPTS / "bw_dedupe_resume_check.py")], 30)

    lines.append("")
    lines.append("Policy: no live D: My Drive; no purge; copy-only; Jeff entity interviews for queue.")
    lines.append("[[Operations/G-to-K-Drain-Assurance-2026-07-10]]")
    lines.append("[[Operations/Entity-Mining-and-Human-Thin-Queue-CANONICAL-2026-07-10]]")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "inventory": code,
                "drain": code2,
                "rehome": code3,
                "entity": code4,
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0 if code2 == 0 else code2


if __name__ == "__main__":
    raise SystemExit(main())
