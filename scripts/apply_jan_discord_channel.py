#!/usr/bin/env python3
"""Apply Jan Library Discord channel wiring once Jeff creates the channel.

Usage:
  python D:/HermesData/scripts/apply_jan_discord_channel.py --channel-id 1234567890123456789
  python D:/HermesData/scripts/apply_jan_discord_channel.py --channel-id 123... --also-free-response

- Backs up ~/.hermes/config.yaml
- Sets discord.channel_prompts[id] to Jan SOUL curator prompt
- Optionally adds channel to free_response_channels
- Does NOT restart gateway (Jeff travel-safe; restart only with green light)
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import yaml

CFG = Path.home() / ".hermes" / "config.yaml"

JAN_PROMPT = """JAN'S LIBRARY CHANNEL — Hermes curator only (never impersonate Jan/Jeff/anyone).
Read and obey SOUL at D:/PhronesisVault/Operations/SOUL-Jan-Library-Agent-2026-07-14.md
For answers: run `python D:/HermesData/scripts/talk_to_jan.py "<user question without /jan prefix>"` and return that grounded reply (or paraphrase warmly with same citations).
Family wording: Gary in manuscripts = Daddy in family chat. Living fact: Mighty Whitey retired; current van Hi-Ho Silver (2015 Chevy Express 3500, ~42-shelf trailer) — label as family update not page quote.
Strip leading `/jan` if present. Ultra-brief chat OK; full substance may stay in reply. No main-silo medical digressions unless asked.
Dream context: Jan hopes to merge her work into one new book someday — outline from corpus only if asked; never write as her.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-id", required=True, help="Discord channel or thread ID")
    ap.add_argument(
        "--also-free-response",
        action="store_true",
        help="Allow replies without @mention in this channel",
    )
    args = ap.parse_args()
    cid = str(args.channel_id).strip()
    if not cid.isdigit():
        print("channel-id must be numeric Discord snowflake")
        return 2
    if not CFG.exists():
        print("missing config", CFG)
        return 1
    bak = CFG.with_suffix(
        CFG.suffix + f".pre-jan-discord-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    )
    shutil.copy(CFG, bak)
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8")) or {}
    disc = cfg.setdefault("discord", {})
    prompts = disc.setdefault("channel_prompts", {})
    if not isinstance(prompts, dict):
        prompts = {}
        disc["channel_prompts"] = prompts
    prompts[cid] = JAN_PROMPT
    if args.also_free_response:
        fr = disc.get("free_response_channels") or ""
        if isinstance(fr, str):
            parts = [p.strip() for p in fr.split(",") if p.strip()]
            if cid not in parts:
                parts.append(cid)
            disc["free_response_channels"] = ",".join(parts)
        elif isinstance(fr, list):
            if cid not in fr:
                fr.append(cid)
            disc["free_response_channels"] = fr
    CFG.write_text(
        yaml.dump(cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        json_dumps(
            {
                "ok": True,
                "channel_id": cid,
                "backup": str(bak),
                "free_response": bool(args.also_free_response),
                "note": "Restart gateway only with Jeff green light for prompt to bind to live sessions.",
            }
        )
    )
    return 0


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
