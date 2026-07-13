#!/usr/bin/env python3
"""Single-pulse kitchen scoreboard — one JSON/MD snapshot for Discord or vault.

No LLM. Safe to run every tick.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RECEIPT_MD = Path(r"D:/PhronesisVault/Operations/logs/silo-scoreboard-pulse-latest.md")
RECEIPT_JSON = Path(r"D:/HermesData/state/silo_scoreboard_pulse.json")
HB = Path(r"D:/HermesData/state/silo_tick_heartbeat.json")
CONT = Path(r"D:/HermesData/state/silo_continuous_state.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ocr = {}
    try:
        c = sqlite3.connect(r"D:/HermesData/state/ocr_backlog.sqlite3", timeout=30)
        ocr = dict(c.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
        c.close()
    except Exception as e:
        ocr = {"error": str(e)}
    reg = {}
    try:
        c = sqlite3.connect(r"D:/HermesData/state/ingest_registry.sqlite3", timeout=60)
        reg["total"] = c.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
        reg["inbox"] = c.execute(
            "SELECT COUNT(*) FROM ingest WHERE domain LIKE '%Inbox%'"
        ).fetchone()[0]
        for label, q in (
            ("medical", "domain LIKE '%Medical%'"),
            ("navy", "domain LIKE '%Navy%'"),
            ("footprint", "domain LIKE '%Footprint%'"),
            ("life", "domain LIKE '%Life-Archive%'"),
        ):
            reg[label] = c.execute(f"SELECT COUNT(*) FROM ingest WHERE {q}").fetchone()[0]
        c.close()
    except Exception as e:
        reg = {"error": str(e)}
    hb = {}
    if HB.is_file():
        try:
            hb = json.loads(HB.read_text(encoding="utf-8"))
        except Exception:
            pass
    cont = {}
    if CONT.is_file():
        try:
            cont = json.loads(CONT.read_text(encoding="utf-8"))
        except Exception:
            pass
    snap = {
        "at": utc(),
        "ocr": ocr,
        "registry": reg,
        "heartbeat": hb,
        "continuous_keys": list(cont.keys())[:12],
        "ok_text": ocr.get("ok_text"),
        "queued": ocr.get("queued"),
        "inbox": reg.get("inbox"),
    }
    RECEIPT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_JSON.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    RECEIPT_MD.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_MD.write_text(
        f"""# Silo scoreboard pulse — {snap['at']}

| Metric | Value |
|--------|------:|
| Registry | {reg.get('total')} |
| Inbox | {reg.get('inbox')} |
| Medical | {reg.get('medical')} |
| Navy | {reg.get('navy')} |
| OCR ok_text | {ocr.get('ok_text')} |
| OCR queued | {ocr.get('queued')} |
| needs_ocr | {ocr.get('needs_ocr')} |

Heartbeat: `{hb.get('phase') or hb.get('status') or 'n/a'}`
""",
        encoding="utf-8",
    )
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
