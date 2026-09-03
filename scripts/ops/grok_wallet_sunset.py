#!/usr/bin/env python3
"""After xAI wallet death, unpin Discord hire room and kill Grok consult hops.

Cutoff: 2026-09-03 00:00 America/New_York (04:00Z). Same wallet as Heavy/4.5/4.6/
Build/Composer. Garden/RP stay local. Does not delete config backups.

  python D:\\HermesData\\scripts\\ops\\grok_wallet_sunset.py
  python D:\\HermesData\\scripts\\ops\\grok_wallet_sunset.py --force
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

CFG = Path(r"D:\HermesData\config.yaml")
STATE = Path(r"D:\HermesData\state")
STAMP = STATE / "grok_wallet_sunset.json"
# Midnight Eastern on 2026-09-03.
CUTOFF = datetime(2026, 9, 3, 4, 0, 0, tzinfo=timezone.utc)
HIRE = "1524846849360531456"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def due(force: bool) -> bool:
    if force:
        return True
    return datetime.now(timezone.utc) >= CUTOFF


def already() -> bool:
    if not STAMP.is_file():
        return False
    try:
        rec = json.loads(STAMP.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(rec.get("applied"))


def apply() -> dict:
    text = CFG.read_text(encoding="utf-8")
    bak = CFG.with_name("config.yaml.bak-wallet-sunset-" + utc()[:19].replace(":", ""))
    shutil.copy2(CFG, bak)
    n = 0

    def sub(old: str, new: str) -> None:
        nonlocal text, n
        if old in text and old != new:
            text = text.replace(old, new, 1)
            n += 1

    # Live comment (2026-09-03) plus the original wording.
    sub(
        f"    '{HIRE}': Grok coord hire. grok-4.6 until 2026-09-03 00:00 America/New_York.",
        f"    '{HIRE}': Grok coord = LOCAL Alice after xAI wallet sunset. Was grok-4.6 hire.",
    )
    sub(
        f"    '{HIRE}': Grok coord = named Grok 4.6 hire surface (model grok-4.6).",
        f"    '{HIRE}': Grok coord = LOCAL Alice after xAI wallet sunset. Was grok-4.6 hire.",
    )
    sub(
        f"""    '{HIRE}':
      model: grok-4.6
      provider: xai-oauth
      context_length: 500000""",
        f"""    '{HIRE}':
      model: phronesis-sovereign-auto
      provider: custom:phronesis-sovereign
      context_length: 131072""",
    )
    sub("      novel_high_value: grok_first_via_proxy_t3", "      novel_high_value: local_then_free")
    # Stop 401 refresh storms after the wallet dies. Pin rewrite is disk;
    # already() stamp makes later daemon ticks a no-op (no rewrite loop).
    sub("  oauth_refresh_on_auth_fail: true", "  oauth_refresh_on_auth_fail: false")
    for label in ("Grok:", "Grok + Phronesis:", "Just xAi:"):
        sub(f"    {label}\n      enabled: true", f"    {label}\n      enabled: false")
        sub(f"  {label}\n    enabled: true", f"  {label}\n    enabled: false")
    CFG.write_text(text, encoding="utf-8")
    rec = {"ts": utc(), "applied": True, "edits": n, "bak": str(bak), "hire": HIRE, "cutoff": CUTOFF.isoformat()}
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if already():
        print("GROK_WALLET_SUNSET already", flush=True)
        return 0
    if not due(args.force):
        left = CUTOFF - datetime.now(timezone.utc)
        print(
            "GROK_WALLET_SUNSET waiting_s=" + str(int(left.total_seconds())) + " hire_still=grok-4.6",
            flush=True,
        )
        return 0
    rec = apply()
    print("GROK_WALLET_SUNSET " + json.dumps({k: rec[k] for k in ("applied", "edits", "hire")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
