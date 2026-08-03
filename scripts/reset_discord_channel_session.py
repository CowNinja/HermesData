#!/usr/bin/env python3
"""Force-reset Hermes Discord channel/thread session(s).

Clears durable SQLite sessions AND rotates sticky sessions.json mapping so the
next Discord turn cannot reuse an ended/deleted transcript. Prefer Discord
slash /reset when the gateway is healthy; use this when slash fails (gateway
down, thrash, or sticky poison).

Usage:
  python D:\\HermesData\\scripts\\reset_discord_channel_session.py 1533447417524125796
  python D:\\HermesData\\scripts\\reset_discord_channel_session.py 1533447417524125796 --post
  python D:\\HermesData\\scripts\\reset_discord_channel_session.py 1533447417524125796 --dry-run

After force-reset while the gateway was already running, restart it so the
in-memory SessionStore + agent cache reload:
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\\HermesData\\scripts\\Start-HermesGateway-Reliable.ps1 -Force
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

HERMES = Path(r"D:\HermesData\hermes-agent")
HERMES_HOME = Path(r"D:\HermesData")
ENV = HERMES_HOME / ".env"
SESSIONS_JSON = HERMES_HOME / "sessions" / "sessions.json"
DB_CANDIDATES = [
    HERMES_HOME / "state.db",
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
    out: list[str] = []
    for (sid,) in rows:
        if sid and sid not in out:
            out.append(str(sid))
    return out


def find_sticky_keys(channel_id: str) -> list[str]:
    if not SESSIONS_JSON.is_file():
        return []
    try:
        data = json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        # Some layouts store the map at top level
        entries = data if isinstance(data, dict) else {}
    keys: list[str] = []
    for k, v in entries.items():
        if k in {"sessions", "version", "updated_at"}:
            continue
        blob = f"{k} {json.dumps(v, default=str)}"
        if channel_id in blob:
            keys.append(str(k))
    return keys


def _new_session_id() -> str:
    now = datetime.now()
    return f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def rotate_sticky_sessions(channel_id: str) -> dict:
    """Rotate sessions.json sticky keys for this channel; return summary."""
    if not SESSIONS_JSON.is_file():
        return {"rotated": [], "path": str(SESSIONS_JSON), "error": "missing"}

    raw = SESSIONS_JSON.read_text(encoding="utf-8")
    data = json.loads(raw)
    # Support both {"sessions": {key: entry}} and flat {key: entry}
    if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
        entries = data["sessions"]
        container = "sessions"
    elif isinstance(data, dict):
        entries = data
        container = "root"
    else:
        return {"rotated": [], "path": str(SESSIONS_JSON), "error": "bad_shape"}

    rotated: list[dict] = []
    now = datetime.now()
    now_iso = now.isoformat()
    for key, entry in list(entries.items()):
        if key in {"sessions", "version", "updated_at"}:
            continue
        blob = f"{key} {json.dumps(entry, default=str)}"
        if channel_id not in blob:
            continue
        if not isinstance(entry, dict):
            continue
        old_sid = entry.get("session_id")
        new_sid = _new_session_id()
        new_entry = {
            "session_key": entry.get("session_key") or key,
            "session_id": new_sid,
            "created_at": now_iso,
            "updated_at": now_iso,
            "display_name": entry.get("display_name"),
            "platform": entry.get("platform"),
            "chat_type": entry.get("chat_type"),
            "is_fresh_reset": True,
            "suspended": False,
            "resume_pending": False,
            "expiry_finalized": False,
            "model_override": None,
        }
        # Preserve origin so routing stays correct
        if "origin" in entry:
            new_entry["origin"] = entry["origin"]
        entries[key] = new_entry
        rotated.append(
            {
                "session_key": key,
                "old_session_id": old_sid,
                "new_session_id": new_sid,
            }
        )

    if rotated:
        bak = SESSIONS_JSON.with_suffix(
            f".json.bak-force-reset-{now.strftime('%Y%m%d%H%M%S')}"
        )
        bak.write_text(raw, encoding="utf-8")
        tmp = SESSIONS_JSON.with_suffix(".json.tmp")
        if container == "sessions":
            data["sessions"] = entries
            out_obj = data
        else:
            out_obj = entries
        tmp.write_text(json.dumps(out_obj, indent=2), encoding="utf-8")
        tmp.replace(SESSIONS_JSON)

    return {
        "rotated": rotated,
        "path": str(SESSIONS_JSON),
        "backup": str(bak) if rotated else None,
    }


def delete_ids(session_ids: list[str]) -> list[str]:
    sys.path.insert(0, str(HERMES))
    from hermes_state import SessionDB

    db = SessionDB()
    deleted: list[str] = []
    for sid in session_ids:
        try:
            if db.delete_session(sid, sessions_dir=HERMES_HOME / "sessions"):
                deleted.append(sid)
        except Exception as e:
            print(f"delete_err {sid}: {type(e).__name__}: {e}")
    return deleted


def create_fresh_db_rows(rotated: list[dict]) -> list[str]:
    """Insert empty live rows for newly rotated sticky session ids."""
    if not rotated:
        return []
    sys.path.insert(0, str(HERMES))
    from hermes_state import SessionDB

    db = SessionDB()
    created: list[str] = []
    for item in rotated:
        sid = item.get("new_session_id")
        skey = item.get("session_key")
        if not sid:
            continue
        try:
            # create_session signature varies; use minimal kwargs via SQL fallback
            con = sqlite3.connect(str(_db_path()), timeout=60)
            con.execute("PRAGMA busy_timeout=60000")
            now = time.time()
            # chat/thread from session_key when possible
            chat_id = None
            thread_id = None
            parts = str(skey or "").split(":")
            # agent:main:discord:thread:<chat>:<thread>
            if len(parts) >= 6 and parts[3] == "thread":
                chat_id = parts[4]
                thread_id = parts[5]
            elif len(parts) >= 5:
                chat_id = parts[-1]
            con.execute(
                "INSERT OR IGNORE INTO sessions "
                "(id, source, session_key, chat_id, thread_id, chat_type, "
                "started_at, ended_at, end_reason) "
                "VALUES (?, 'discord', ?, ?, ?, 'thread', ?, NULL, NULL)",
                (sid, skey, chat_id, thread_id, now),
            )
            con.commit()
            con.close()
            created.append(sid)
        except Exception as e:
            print(f"create_err {sid}: {type(e).__name__}: {e}")
            try:
                db  # silence lint
            except Exception:
                pass
    return created


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
    sticky = find_sticky_keys(cid)
    print(
        json.dumps(
            {
                "channel_id": cid,
                "found": found,
                "sticky_keys": sticky,
                "db": str(_db_path()),
                "sessions_json": str(SESSIONS_JSON),
            },
            indent=2,
        )
    )
    if args.dry_run:
        return 0

    deleted = delete_ids(found)
    sticky_result = rotate_sticky_sessions(cid)
    created = create_fresh_db_rows(sticky_result.get("rotated") or [])
    print(
        json.dumps(
            {
                "deleted": deleted,
                "sticky": sticky_result,
                "created_fresh": created,
            },
            indent=2,
        )
    )
    if args.post:
        n_del = len(deleted)
        n_rot = len(sticky_result.get("rotated") or [])
        msg = (
            f"**[Session force-reset]** Thread `{cid}` cleared "
            f"(deleted {n_del} session id(s), rotated {n_rot} sticky key(s)). "
            "Transcript wiped. Identity/channel prompt still applies. "
            "Send a short next message to start clean. "
            "If slash /reset still fails, gateway may be down - ops restart first."
        )
        mid = post_discord(cid, msg)
        print(json.dumps({"discord_message_id": mid}))
    print(
        "NOTE: If the gateway was already running, restart it so in-memory "
        "session/agent cache reloads:\n"
        "  powershell -NoProfile -ExecutionPolicy Bypass -File "
        "D:\\HermesData\\scripts\\Start-HermesGateway-Reliable.ps1 -Force"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
