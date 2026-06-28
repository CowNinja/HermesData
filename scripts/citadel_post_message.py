#!/usr/bin/env python3
"""Post a message to a Citadel Discord channel (bot token)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ENV_FILE = Path(r"D:\HermesData\.env")
API = "https://discord.com/api/v10"


def token() -> str:
    if os.getenv("DISCORD_BOT_TOKEN"):
        return os.getenv("DISCORD_BOT_TOKEN", "").strip()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no token")


def post(channel_id: str, content: str) -> dict:
    data = json.dumps({"content": content[:2000]}).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bot {token()}",
            "Content-Type": "application/json",
            "User-Agent": "PhronesisCitadelOrchestrator/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: citadel_post_message.py <channel_id> <message>")
        raise SystemExit(2)
    result = post(sys.argv[1], " ".join(sys.argv[2:]))
    print(json.dumps({"ok": True, "id": result.get("id")}))
