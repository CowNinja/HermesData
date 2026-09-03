#!/usr/bin/env python3
"""Dry-run Discord intake hydrate + mouth-bind + collapse. No :8090."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HERMES = Path(r"D:\HermesData")
AGENT = HERMES / "hermes-agent"
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(HERMES / "scripts"))
sys.path.insert(0, str(HERMES / "scripts" / "ops"))

from gateway.discord_intake import hydrate_discord_intake_history  # noqa: E402
from discord_mouth_bind import filter_outbound_status  # noqa: E402
from plugins.platforms.discord.adapter import (  # noqa: E402
    _collapse_repetitive_discord_content,
)


def _discord_event():
    return SimpleNamespace(source=SimpleNamespace(platform=SimpleNamespace(value="discord")))


def test_hydrate_synthetic() -> dict:
    hist = [{"role": "system", "content": "THREAD ANCHOR"}]
    hist.append({"role": "system", "content": "[RELEVANT ENTITY CONTEXT]\nstale"})
    for i in range(40):
        hist.append({"role": "user" if i % 2 == 0 else "assistant", "content": "t%d" % i})
    entry = SimpleNamespace(session_id="synth", platform="discord", updated_at=datetime.now(timezone.utc))
    out = hydrate_discord_intake_history(hist, session_entry=entry, event=_discord_event())
    nonsys = [m for m in out if m.get("role") != "system"]
    return {
        "kept": len(out),
        "nonsys": len(nonsys),
        "has_anchor": any("ANCHOR" in str(m.get("content")) for m in out),
        "stale_dropped": not any("[RELEVANT ENTITY CONTEXT]" in str(m.get("content")) for m in out),
        "ok": len(nonsys) == 16 and len(out) <= 18,
    }


def test_hydrate_thread3() -> dict:
    sid = "20260901_124841_e4947ebe"
    db_paths = [
        HERMES / "state.db",
        Path.home() / ".hermes" / "state.db",
        HERMES / "hermes-agent" / "state.db",
    ]
    db = next((p for p in db_paths if p.is_file()), None)
    if db is None:
        return {"ok": False, "error": "no_state_db", "skipped": True}
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT role, content FROM messages WHERE session_id=? AND COALESCE(active,1)=1 ORDER BY id",
            (sid,),
        )
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)[:160], "db": str(db)}
    finally:
        conn.close()
    if not rows:
        # try json content column variants
        return {"ok": False, "error": "no_rows", "db": str(db), "sid": sid}
    hist = [{"role": r[0] or "user", "content": r[1] or ""} for r in rows]
    idle_entry = SimpleNamespace(
        session_id=sid,
        platform="discord",
        updated_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    out = hydrate_discord_intake_history(hist, session_entry=idle_entry, event=_discord_event())
    nonsys = [m for m in out if str(m.get("role")) != "system"]
    return {
        "db": str(db),
        "orig": len(hist),
        "kept": len(out),
        "nonsys": len(nonsys),
        "ok": len(nonsys) <= 16 and len(out) <= 18,
    }


def test_banners() -> dict:
    samples = [
        "ℹ️ Context compression deferred — summary still streaming. Continuing without compression this turn.",
        "⚠ Compression aborted: Context compression summary was truncated (finish_reason=length): generation hit the output token cap",
        "⚠ Context is over the compression threshold (~193,219 tokens >= 92,160) but compression is currently blocked (cooldown:30).",
        "Hey Dad, three revocable living trusts.",
    ]
    acts = [filter_outbound_status(s)[1] for s in samples]
    return {
        "acts": acts,
        "ok": acts[:3] == ["drop", "drop", "drop"] and acts[3] == "pass",
    }


def test_collapse_parts() -> dict:
    text = (
        "### Part 1: FLL SPIKE Prime\n\nGyro drift paragraph one.\n\n"
        "### Part 2: Albion Online Crafting Focus Calculations\n\n"
        "Focus math paragraph two is distinct and must survive.\n"
    )
    out = _collapse_repetitive_discord_content(text * 2, soft_cap=400)
    return {
        "kept_albion": "Albion" in out,
        "no_trim_footer": "...(trimmed long/repeated reply)" not in out,
        "ok": "Albion" in out and "...(trimmed long/repeated reply)" not in out,
    }


def main() -> int:
    doc = {
        "hydrate_synth": test_hydrate_synthetic(),
        "hydrate_thread3": test_hydrate_thread3(),
        "banners": test_banners(),
        "collapse_parts": test_collapse_parts(),
    }
    doc["ok"] = all(
        bool((doc[k] or {}).get("ok") or (doc[k] or {}).get("skipped"))
        for k in ("hydrate_synth", "hydrate_thread3", "banners", "collapse_parts")
    ) and doc["hydrate_synth"]["ok"] and doc["banners"]["ok"] and doc["collapse_parts"]["ok"]
    print(json.dumps(doc, indent=2))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
