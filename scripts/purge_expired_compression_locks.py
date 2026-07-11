#!/usr/bin/env python3
"""Remove expired compression_locks rows from Hermes state.db."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

STATE_DB = Path(r"D:\HermesData\state.db")


def main() -> int:
    if not STATE_DB.is_file():
        print(f"SKIP: no state.db at {STATE_DB}")
        return 0
    now = int(time.time())
    con = sqlite3.connect(STATE_DB)
    try:
        cur = con.execute("SELECT COUNT(*) FROM compression_locks WHERE expires_at < ?", (now,))
        count = int(cur.fetchone()[0])
        if count:
            con.execute("DELETE FROM compression_locks WHERE expires_at < ?", (now,))
            con.commit()
        print(f"purged={count} expired compression_locks (before {now})")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())