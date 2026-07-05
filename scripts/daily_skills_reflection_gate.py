#!/usr/bin/env python3
"""Daily skills reflection gate -- no_agent cron leaf.

Avoids LLM truncation on Daily-Skills-Reflection by doing a deterministic
vault scan. Emits [SILENT] when nothing changed; one-line summary otherwise.
Full wisdom-keeper LLM reflection remains available via manual / ad-hoc run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILLS_USAGE = Path(r"D:\HermesData\skills\.usage.json")
LIBRARIAN_CHANGELOG = Path(r"D:\HermesData\skills\.librarian_changelog.json")
EVO_LOG = Path(r"D:\PhronesisVault\Operations\Autonomous-Evolution-Log-2026-07-04.md")


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _recent_usage(hours: int = 26) -> int:
    data = _load_json(SKILLS_USAGE)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    for _skill, meta in (data or {}).items():
        if not isinstance(meta, dict):
            continue
        ts = meta.get("last_used") or meta.get("updated_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                count += 1
        except Exception:
            continue
    return count


def _changelog_entries(hours: int = 26) -> int:
    data = _load_json(LIBRARIAN_CHANGELOG)
    entries = data.get("entries") or data.get("changes") or []
    if not isinstance(entries, list):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    n = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        ts = e.get("timestamp") or e.get("at")
        if not ts:
            n += 1
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                n += 1
        except Exception:
            n += 1
    return n


def main() -> int:
    used = _recent_usage()
    changes = _changelog_entries()
    if used == 0 and changes == 0:
        print("[SILENT] No skill usage or librarian changes in last 26h -- skip LLM reflection.")
        return 0
    line = (
        f"Skills reflection gate: {used} skills used, {changes} librarian changes (26h). "
        "Run ad-hoc wisdom-keeper if deep patch needed."
    )
    print(line)
    if EVO_LOG.is_file():
        try:
            with open(EVO_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n- **Skills gate** {datetime.now(timezone.utc).strftime('%H:%M UTC')}: {line}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())