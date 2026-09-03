#!/usr/bin/env python3
"""Fetch last N Discord messages from three live threads. No POST. No token print."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENV = Path(r"D:\HermesData\.env")
API = "https://discord.com/api/v10"
OUT = Path(r"D:\HermesData\state\inspect_three_threads_latest.json")
THREADS = [
    ("1536837688215343284", "model-mgmt / #hermes topic"),
    ("1524846849360531456", "Grok coord / hire"),
    ("1544388532544471151", "VA estate-planning"),
]
_TOOL_LEAK = re.compile(
    r"(\[Called\s|</?tool_call>|Traceback \(most recent call last\)|"
    r'"success": (true|false)|GOLDEN TOOL|QWYTHOS 9B SYSTEM PRIMER)',
    re.I,
)
_BANNER = re.compile(
    r"(Status:|Urgent Triage|Message-ID:|The Play:|Prompt Strategy|Wait —|compacting context)",
    re.I,
)


def token() -> str:
    t = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if t:
        return t
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no DISCORD_BOT_TOKEN")


def api_get(path: str) -> object:
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": "Bot " + token(), "User-Agent": "PhronesisThreadInspect/1.0"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def flags(text: str, is_bot: bool) -> list[str]:
    raw = text or ""
    out: list[str] = []
    if not is_bot:
        return out
    n = len(raw)
    if n >= 1990:
        out.append("near_discord_cap:%d" % n)
    if _TOOL_LEAK.search(raw):
        out.append("tool_or_prompt_leak")
    if _BANNER.search(raw):
        out.append("system_banner")
    if n >= 400 and raw.rstrip()[-1:].isalnum() and not raw.rstrip().endswith((".", "!", "?", "`", "*", '"', "'")):
        out.append("possible_midword_cut")
    if "_(cut at token ceiling" in raw:
        out.append("token_ceiling_continue_cue")
    if "Response truncated" in raw:
        out.append("split_cap_notice")
    return out


def main() -> int:
    rows = []
    for tid, label in THREADS:
        time.sleep(0.2)
        rec: dict = {"id": tid, "label": label}
        try:
            ch = api_get("/channels/" + tid)
        except urllib.error.HTTPError as exc:
            rec["error"] = "channel %s" % exc.code
            rows.append(rec)
            continue
        rec["name"] = (ch or {}).get("name")
        rec["parent_id"] = (ch or {}).get("parent_id")
        rec["type"] = (ch or {}).get("type")
        try:
            msgs = api_get("/channels/%s/messages?limit=10" % tid)
        except urllib.error.HTTPError as exc:
            rec["error"] = "messages %s" % exc.code
            rows.append(rec)
            continue
        if not isinstance(msgs, list):
            rec["error"] = "bad_messages"
            rows.append(rec)
            continue
        msgs.sort(key=lambda m: str(m.get("id") or ""))
        turns = []
        for m in msgs:
            author = m.get("author") or {}
            content = str(m.get("content") or "")
            is_bot = bool(author.get("bot"))
            turns.append(
                {
                    "id": m.get("id"),
                    "ts": m.get("timestamp"),
                    "bot": is_bot,
                    "username": author.get("username"),
                    "len": len(content),
                    "atts": len(m.get("attachments") or []),
                    "flags": flags(content, is_bot),
                    "text": content[:1200],
                }
            )
        rec["n"] = len(turns)
        rec["turns"] = turns
        rows.append(rec)
    doc = {"ts": datetime.now(timezone.utc).isoformat(), "threads": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "n": [t.get("n") for t in rows]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
