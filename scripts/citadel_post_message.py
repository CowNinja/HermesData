#!/usr/bin/env python3
"""Post a message to a Citadel Discord channel (bot token).

For kitchen/ops posts prefer ops_discord_post.py (auto [GROK OPS] + dual-beauty guard).
This low-level post() does not force prefix so helpers can compose bodies.
CLI: optional --ops-prefix (default on) and --no-ops-prefix.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ENV_FILE = Path(r"D:\HermesData\.env")
API = "https://discord.com/api/v10"
OPS_PREFIX = "[GROK OPS]"


def token() -> str:
    if os.getenv("DISCORD_BOT_TOKEN"):
        return os.getenv("DISCORD_BOT_TOKEN", "").strip()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no token")


def ensure_ops_prefix(content: str) -> str:
    c = (content or "").strip()
    if not c:
        return OPS_PREFIX
    if c.startswith(OPS_PREFIX) or c.upper().startswith("GROK OPS"):
        return c
    return OPS_PREFIX + " " + c


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
    argv = sys.argv[1:]
    ops_prefix = True
    if "--no-ops-prefix" in argv:
        ops_prefix = False
        argv = [a for a in argv if a != "--no-ops-prefix"]
    if "--ops-prefix" in argv:
        ops_prefix = True
        argv = [a for a in argv if a != "--ops-prefix"]
    if len(argv) < 2:
        print(
            "usage: citadel_post_message.py [--ops-prefix|--no-ops-prefix] "
            "<channel_id> <message>"
        )
        raise SystemExit(2)
    channel_id = argv[0]
    msg = " ".join(argv[1:])
    if ops_prefix:
        msg = ensure_ops_prefix(msg)
    result = post(channel_id, msg)
    print(json.dumps({"ok": True, "id": result.get("id"), "ops_prefix": ops_prefix}))
