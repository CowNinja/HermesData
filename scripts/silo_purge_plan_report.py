#!/usr/bin/env python3
"""Read-only purge plan report — NEVER deletes."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
OUT = Path(r"D:/PhronesisVault/Operations/logs/silo-purge-plan-report-latest.md")


def main() -> int:
    con = sqlite3.connect(str(REG), timeout=60)
    total = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    with_dest = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE dest_path IS NOT NULL AND dest_path!=''"
    ).fetchone()[0]
    ok = miss = 0
    for (dest,) in con.execute(
        "SELECT dest_path FROM ingest WHERE dest_path IS NOT NULL ORDER BY RANDOM() LIMIT 50"
    ):
        if dest and Path(dest).is_file():
            ok += 1
        else:
            miss += 1
    now = datetime.now(timezone.utc).isoformat()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        f"""# Purge plan report (READ-ONLY) — {now}

**NOT ARMED. No deletions.**

| Check | Value |
|-------|------:|
| Registry total | {total} |
| With dest_path | {with_dest} |
| Spot dest exists (50) | {ok}/{ok+miss} |
| Jeff green light | required: `purge drive OK` |

See [[Operations/Purge-Plan-Prep-CANONICAL-2026-07-14]]
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "total": total,
                "dest_ok_sample": ok,
                "dest_miss_sample": miss,
                "receipt": str(OUT),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
