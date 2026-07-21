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
    """Soft-fail catalog hygiene. Never crash orch on lock busy.

    2026-07-21: land writer races caused uncaught sqlite lock → exit 1.
    Lessons: busy_timeout + BEGIN IMMEDIATE retry; always write receipt;
    exit 0 on partial progress / lock skip (soft-ok factory).
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=4000)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    now = utc()
    total = 0
    inbox = None
    err = None
    try:
        con = sqlite3.connect(str(DB), timeout=120)
        con.execute("PRAGMA busy_timeout=120000")
        for r in range(args.rounds):
            try:
                rows = con.execute(
                    """SELECT id, dest_path, sha256 FROM ingest
                       WHERE domain LIKE '%Inbox%' AND dest_path IS NOT NULL
                       LIMIT ?""",
                    (args.batch,),
                ).fetchall()
            except sqlite3.Error as e:
                err = f"select_round_{r}:{e}"
                break
            if not rows:
                break
            fixed = 0
            for id_, dest, sha in rows:
                try:
                    if Path(dest).is_file():
                        continue
                except Exception:
                    pass
                if not sha:
                    continue
                try:
                    alt = con.execute(
                        """SELECT dest_path, domain FROM ingest
                           WHERE sha256=? AND domain NOT LIKE '%Inbox%'
                             AND dest_path IS NOT NULL LIMIT 1""",
                        (sha,),
                    ).fetchone()
                except sqlite3.Error:
                    continue
                if alt and Path(alt[0]).is_file():
                    try:
                        con.execute(
                            "UPDATE ingest SET domain=?, dest_path=?, last_seen=? WHERE id=?",
                            (alt[1], alt[0], now, id_),
                        )
                        fixed += 1
                    except sqlite3.Error:
                        continue
            try:
                con.commit()
            except sqlite3.Error as e:
                err = f"commit_round_{r}:{e}"
                break
            total += fixed
            if fixed == 0:
                break
        try:
            inbox = con.execute(
                "SELECT COUNT(*) FROM ingest WHERE domain LIKE '%Inbox%'"
            ).fetchone()[0]
        except sqlite3.Error as e:
            err = (err or "") + f";inbox_count:{e}"
        try:
            con.close()
        except Exception:
            pass
    except Exception as e:
        err = str(e)[:240]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"# Inbox ghost repoint — {now}\n\n"
        f"**Repointed:** {total} · **Inbox now:** {inbox}\n"
        + (f"\n_soft_err:_ `{err}`\n" if err else ""),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "repointed": total,
                "inbox_now": inbox,
                "soft_err": err,
                "receipt": str(RECEIPT),
            }
        )
    )
    # Always 0 — orch soft-ok; lock races are expected under land writer
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
