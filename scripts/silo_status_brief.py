#!/usr/bin/env python3
"""One-shot silo + stack brief — $0 Grok. For cron no_agent or thin chat pulses."""
from __future__ import annotations

import json
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
STATE = Path(r"D:\HermesData\state\silo_continuous_state.json")
PRIMARY = Path(r"D:\HermesData\state\silo_primary.json")
CENSUS = 164105  # MemoryCard file count measured 2026-07-12


def port(p: int) -> bool:
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", p))
        return True
    except Exception:
        return False
    finally:
        s.close()


def main() -> int:
    lines = [f"# Silo brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]
    lines.append(
        f"**Ports:** gw8642={'UP' if port(8642) else 'DOWN'} · "
        f"qwy8090={'UP' if port(8090) else 'DOWN'} · "
        f"proxy8091={'UP' if port(8091) else 'DOWN'} · "
        f"comfy8188={'UP' if port(8188) else 'DOWN'}"
    )
    if PRIMARY.is_file():
        try:
            sp = json.loads(PRIMARY.read_text(encoding="utf-8"))
            lines.append(f"**silo_primary:** {sp.get('enabled')}")
        except Exception:
            pass
    if STATE.is_file():
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            at = d.get("at", "")
            age = ""
            if at:
                try:
                    dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                    age = f" age={int((datetime.now(timezone.utc) - dt).total_seconds())}s"
                except Exception:
                    pass
            a = d.get("assess") or {}
            lines.append(
                f"**continuous:** cycle={d.get('cycle')} mode={a.get('mode')} "
                f"drain={((d.get('limits') or {}).get('drain'))} qwy={a.get('qwythos_8090')}{age}"
            )
        except Exception as e:
            lines.append(f"**continuous:** err {e}")
    if DB.is_file():
        con = sqlite3.connect(str(DB))
        tot = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
        uniq = con.execute(
            "SELECT COUNT(DISTINCT sha256) FROM ingest WHERE sha256 IS NOT NULL AND sha256!=''"
        ).fetchone()[0]
        arch = con.execute(
            "SELECT COUNT(*) FROM ingest WHERE source_path LIKE '%archive%'"
        ).fetchone()[0]
        inbox = con.execute(
            "SELECT COUNT(*) FROM ingest WHERE domain LIKE '%Inbox%'"
        ).fetchone()[0]
        lines.append(
            f"**registry:** {tot} · unique={uniq} · archive_rows={arch} · "
            f"inbox_domain={inbox} · MemoryCard_file%≈{100 * tot / CENSUS:.1f}%"
        )
        for row in con.execute(
            "SELECT process_status, COUNT(*) FROM ingest GROUP BY 1 ORDER BY 2 DESC"
        ):
            lines.append(f"  - process {row[0]}: {row[1]}")
        con.close()
    lines.append("")
    lines.append("_Script-only brief — no SuperGrok tokens._")
    text = "\n".join(lines)
    out = Path(r"D:\PhronesisVault\Operations\logs\silo-status-brief-latest.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
