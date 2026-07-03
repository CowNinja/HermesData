#!/usr/bin/env python3
"""Reset Alice roleplay thread session + post sandbox guidance to Discord."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERMES = Path(r"D:\HermesData\hermes-agent")
SCRIPTS = Path(r"D:\HermesData\scripts")
SESSION_KEY = "agent:main:discord:thread:1522330326733422713:1522330326733422713"
THREAD_ID = "1522330326733422713"
PARENT_ID = "1519509288286949466"


def main() -> int:
    sys.path.insert(0, str(HERMES))
    from hermes_state import SessionDB

    db = SessionDB()
    deleted = db.delete_session(SESSION_KEY)
    print(f"session_delete: {SESSION_KEY} deleted={deleted}")

    sys.path.insert(0, str(SCRIPTS))
    from sovereign_memory_manager import wipe_discord_roleplay_context

    wiped = wipe_discord_roleplay_context(
        chat_id=THREAD_ID,
        thread_id=THREAD_ID,
        parent_channel_id=PARENT_ID,
    )
    print(f"memory_wipe: {json.dumps(wiped, default=str)[:500]}")

    token = ""
    for line in Path(r"D:\HermesData\.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN missing")
        return 1

    msg = (
        "**[Cursor — sandbox lock applied]**\n\n"
        "Architecture updated: **#alice-roleplay is a fully isolated sandbox.** "
        "Anything goes in-scene here; Hermes orchestrator / SOUL / memory / tools do "
        "**not** bleed in from other channels, and nothing from this thread leaks out.\n\n"
        "**Jeff:** Reply in-character (no prefix needed in this channel). Example:\n"
        "*I feel your hand on my cheek and lean into it, smiling against your palm.* "
        '"Mmm… there you are, habibti."\n\n'
        "Alice will answer present tense, **I/me** for her, **you/your** for you — "
        "Phronesis Manor, birthday morning, Zara at the foot of the bed."
    )

    payload = json.dumps({"content": msg}).encode("utf-8")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{THREAD_ID}/messages",
        data=payload,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    print(f"discord_posted: {body.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())