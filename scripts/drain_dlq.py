#!/usr/bin/env python3
"""Dead-letter queue for G→K drain failures (ETL best practice).

Failed items land in SQLite + optional quarantine note — pipeline keeps moving.
Retry later without blocking the main wave.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\drain_dlq.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\drain-dlq-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS dlq (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_path TEXT NOT NULL,
          dest_path TEXT,
          error TEXT,
          attempts INTEGER DEFAULT 1,
          status TEXT DEFAULT 'open',
          first_seen TEXT,
          last_seen TEXT,
          UNIQUE(source_path, error)
        )
        """
    )
    con.commit()
    return con


def record(source: str, dest: str, error: str) -> None:
    con = connect()
    now = utc()
    row = con.execute(
        "SELECT id, attempts FROM dlq WHERE source_path=? AND error=?",
        (source, error[:500]),
    ).fetchone()
    if row:
        con.execute(
            "UPDATE dlq SET attempts=attempts+1, last_seen=?, dest_path=? WHERE id=?",
            (now, dest, row["id"]),
        )
    else:
        con.execute(
            "INSERT INTO dlq(source_path, dest_path, error, first_seen, last_seen) VALUES (?,?,?,?,?)",
            (source, dest, error[:500], now, now),
        )
    con.commit()
    con.close()


def list_open(limit: int = 50) -> list[dict]:
    con = connect()
    rows = con.execute(
        "SELECT * FROM dlq WHERE status='open' ORDER BY attempts DESC, last_seen DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def stats() -> dict:
    con = connect()
    total = con.execute("SELECT COUNT(*) c FROM dlq").fetchone()["c"]
    open_n = con.execute("SELECT COUNT(*) c FROM dlq WHERE status='open'").fetchone()["c"]
    con.close()
    return {"total": total, "open": open_n, "db": str(DB)}


def write_receipt() -> None:
    st = stats()
    rows = list_open(30)
    lines = [
        f"# Drain DLQ — {utc()}",
        "",
        f"**Open:** {st['open']} / {st['total']}",
        "",
        "| Attempts | Source | Error |",
        "|---------:|--------|-------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['attempts']} | `{Path(r['source_path']).name[:50]}` | {(r['error'] or '')[:60]} |"
        )
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stats", "list", "receipt"])
    args = ap.parse_args()
    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_open(), indent=2))
    else:
        write_receipt()
        print(json.dumps(stats(), indent=2))
    return 0


if __name__ == "__main__":
    from pathlib import Path

    raise SystemExit(main())
