#!/usr/bin/env python3
"""Repoint ghost Inbox registry rows whose dest is gone but same sha256 lives on a shelf.

Does not move files — catalog hygiene only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-inbox-ghost-repoint-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=4000)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    con = sqlite3.connect(str(DB), timeout=300)
    con.execute("PRAGMA busy_timeout=300000")
    total = 0
    now = utc()
    for r in range(args.rounds):
        rows = con.execute(
            """SELECT id, dest_path, sha256 FROM ingest
               WHERE domain LIKE '%Inbox%' AND dest_path IS NOT NULL
               LIMIT ?""",
            (args.batch,),
        ).fetchall()
        if not rows:
            break
        fixed = 0
        for id_, dest, sha in rows:
            if Path(dest).is_file():
                continue
            if not sha:
                continue
            alt = con.execute(
                """SELECT dest_path, domain FROM ingest
                   WHERE sha256=? AND domain NOT LIKE '%Inbox%'
                     AND dest_path IS NOT NULL LIMIT 1""",
                (sha,),
            ).fetchone()
            if alt and Path(alt[0]).is_file():
                con.execute(
                    "UPDATE ingest SET domain=?, dest_path=?, last_seen=? WHERE id=?",
                    (alt[1], alt[0], now, id_),
                )
                fixed += 1
        con.commit()
        total += fixed
        if fixed == 0:
            break
    inbox = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE domain LIKE '%Inbox%'"
    ).fetchone()[0]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"# Inbox ghost repoint — {now}\n\n**Repointed:** {total} · **Inbox now:** {inbox}\n",
        encoding="utf-8",
    )
    print(json.dumps({"repointed": total, "inbox_now": inbox, "receipt": str(RECEIPT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
