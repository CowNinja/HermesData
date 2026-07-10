#!/usr/bin/env python3
"""Autonomous G→K wave runner for no_agent cron.

- Sources: MemoryCard historical Google Drive only (not live D: My Drive)
- Always copy-only with provenance via g_to_k_safe_drain.py
- Default apply small wave; inventory refresh first
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-autonomous-wave-latest.md")
LIMIT = 80  # per autonomous tick


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    lines = [f"# G→K autonomous wave — {ts}", ""]
    # 1 inventory
    code, out = run([sys.executable, str(SCRIPTS / "g_memorycard_inventory.py")], 180)
    code_l, out_l = run([sys.executable, str(SCRIPTS / "lifecycle_index.py"), "inventory",
        "--root", r"G:\MemoryCard_Backups\Google Drive", "--limit", "150"], 300)
    lines.append(f"## Lifecycle inventory exit={code_l}")
    lines.append("```"); lines.append(out_l[-800:]); lines.append("```")
    run([sys.executable, str(SCRIPTS / "lifecycle_index.py"), "queue", "--limit", "80"], 60)

    lines.append(f"## Inventory exit={code}")
    lines.append("```")
    lines.append(out[-1500:])
    lines.append("```")
    # 2 apply wave historical only
    code2, out2 = run(
        [
            sys.executable,
            str(SCRIPTS / "g_to_k_safe_drain.py"),
            "--apply",
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
    lines.append(out2[-2000:])
    lines.append("```")
    lines.append("")
    run([sys.executable, str(SCRIPTS / "dedup_cluster.py"), "--root", r"K:\Phronesis-Sovereign\Personal-Digital-Silo", "--limit", "2000"], 600)
    lines.append("Policy: no live D: My Drive; no purge; copy-only.")
    lines.append("[[Operations/G-to-K-Drain-Assurance-2026-07-10]]")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"inventory": code, "drain": code2, "receipt": str(RECEIPT)}, indent=2))
    return 0 if code2 == 0 else code2


if __name__ == "__main__":
    raise SystemExit(main())
