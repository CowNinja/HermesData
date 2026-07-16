#!/usr/bin/env python3
"""Single-pulse kitchen scoreboard — one JSON/MD snapshot for Discord or vault.

Post-OCR era: includes twin depth (derivative_ok, med index, k_light, BB, OCR open).
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
MED_IDX = Path(r"D:/HermesData/state/medical_navy_text_index.jsonl")
LIGHT = Path(r"D:/HermesData/state/k_light_index.jsonl")
PARKING = Path(r"D:/HermesData/config/future_projects_parking.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_lines(p: Path) -> int:
    if not p.is_file():
        return 0
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def parking_brief() -> dict:
    if not PARKING.is_file():
        return {}
    try:
        doc = json.loads(PARKING.read_text(encoding="utf-8"))
        projects = doc.get("projects") or []
        by = {}
        for p in projects:
            st = p.get("status") or "unknown"
            by[st] = by.get(st, 0) + 1
        return {
            "count": len(projects),
            "by_status": by,
            "focus_now": (doc.get("focus_now") or [])[:4],
        }
    except Exception as e:
        return {"error": str(e)[:120]}


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
        try:
            reg["booksbloom"] = c.execute(
                "SELECT COUNT(*) FROM ingest WHERE process_status='landed_booksbloom_pilot'"
            ).fetchone()[0]
        except Exception:
            reg["booksbloom"] = 0
        try:
            reg["derivative_ok"] = c.execute(
                "SELECT COUNT(*) FROM ingest WHERE process_status='derivative_ok'"
            ).fetchone()[0]
        except Exception:
            reg["derivative_ok"] = 0
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
    ocr_open = int(ocr.get("needs_ocr") or 0) + int(ocr.get("queued") or 0) + int(
        ocr.get("error") or 0
    )
    twin = {
        "med_navy_index": count_lines(MED_IDX),
        "k_light_index": count_lines(LIGHT),
        "derivative_ok": reg.get("derivative_ok"),
        "era": "post_ocr" if ocr_open == 0 else "ocr_drain",
    }
    parking = parking_brief()
    snap = {
        "at": utc(),
        "ocr": ocr,
        "ocr_open": ocr_open,
        "registry": reg,
        "twin": twin,
        "parking": parking,
        "heartbeat": hb,
        "continuous_keys": list(cont.keys())[:12],
        "ok_text": ocr.get("ok_text"),
        "queued": ocr.get("queued"),
        "inbox": reg.get("inbox"),
        "booksbloom": reg.get("booksbloom"),
    }
    RECEIPT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_JSON.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    RECEIPT_MD.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_MD.write_text(
        f"""# Silo scoreboard pulse — {snap['at']}

| Metric | Value |
|--------|------:|
| Era | {twin.get('era')} |
| Registry | {reg.get('total')} |
| Inbox | {reg.get('inbox')} |
| Medical | {reg.get('medical')} |
| Navy | {reg.get('navy')} |
| Booksbloom pilot | {reg.get('booksbloom')} |
| OCR ok_text | {ocr.get('ok_text')} |
| OCR open | {ocr_open} |
| derivative_ok | {reg.get('derivative_ok')} |
| Med/Navy index | {twin.get('med_navy_index')} |
| K-light index | {twin.get('k_light_index')} |
| Parking projects | {parking.get('count')} {parking.get('by_status') or ''} |

Heartbeat: `{hb.get('phase') or hb.get('status') or 'n/a'}`
""",
        encoding="utf-8",
    )
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
