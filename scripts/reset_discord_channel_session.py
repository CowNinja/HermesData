#!/usr/bin/env python3
"""Reset Hermes Discord channel/thread session(s) to clear Grok tool-history poison.

Usage:
  python D:\\HermesData\\scripts\\reset_discord_channel_session.py 1524529242019336434
  python D:\\HermesData\\scripts\\reset_discord_channel_session.py 1524529242019336434 --post

When local Qwythos errors with \"could not load this Grok thread's tool history\",
delete the channel's durable sessions so the next Discord turn starts clean.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

HERMES = Path(r"D:\HermesData\hermes-agent")
ENV = Path(r"D:\HermesData\.env")
DB_CANDIDATES = [
    Path(r"D:\HermesData\state.db"),
    Path(r"C:\Users\CowNi\.hermes\state.db"),
]


def _token() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("DISCORD_BOT_TOKEN missing in D:\\HermesData\\.env")


def _db_path() -> Path:
    for p in DB_CANDIDATES:
        if p.is_file():
            return p
    raise SystemExit("state.db not found")


def find_session_ids(channel_id: str) -> list[str]:
    con = sqlite3.connect(str(_db_path()), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    pat = f"%{channel_id}%"
    rows = con.execute(
        "SELECT id FROM sessions WHERE session_key LIKE ? OR chat_id LIKE ? "
        "OR thread_id LIKE ? OR CAST(chat_id AS TEXT) LIKE ? "
        "OR CAST(thread_id AS TEXT) LIKE ?",
        (pat, pat, pat, pat, pat),
    ).fetchall()
    con.close()
    # preserve order, unique
    out: list[str] = []
    for (sid,) in rows:
        if sid and sid not in out:
            out.append(str(sid))
    return out


def delete_ids(session_ids: list[str]) -> list[str]:
    sys.path.insert(0, str(HERMES))
    from hermes_state import SessionDB

    db = SessionDB()
    deleted: list[str] = []
    for sid in session_ids:
        try:
            if db.delete_session(sid):
                deleted.append(sid)
        except Exception as e:
            print(f"delete_err {sid}: {type(e).__name__}: {e}")
    return deleted


def post_discord(channel_id: str, content: str) -> str:
    payload = json.dumps({"content": content[:1900]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bot {_token()}",
            "Content-Type": "application/json",
            "User-Agent": "PhronesisSessionReset/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return str(json.loads(resp.read().decode("utf-8")).get("id") or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("channel_id", help="Discord channel or thread snowflake")
    ap.add_argument(
        "--post",
        action="store_true",
        help="Post a short notice to the channel after reset",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cid = str(args.channel_id).strip()
    found = find_session_ids(cid)
    print(json.dumps({"channel_id": cid, "found": found, "db": str(_db_path())}, indent=2))
    if args.dry_run:
        return 0
    deleted = delete_ids(found)
    print(json.dumps({"deleted": deleted}, indent=2))
    if args.post:
        msg = (
            f"**[Session reset]** Hermes sessions for `{cid}` cleared "
            f"({len(deleted)} id(s)). Re-ask a short prompt — avoids Grok tool-history "
            "parser errors on local Qwythos."
        )
        mid = post_discord(cid, msg)
        print(json.dumps({"discord_message_id": mid}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
