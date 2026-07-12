#!/usr/bin/env python3
"""Timeline harvest — dated life events from paths + OCR for Medical/Navy/etc."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
OUT = Path(r"D:\HermesData\state\timelines")
VAULT = Path(r"D:\PhronesisVault\Operations\logs")
DATE_RE = re.compile(
    r"(?P<iso>20\d{2}-\d{2}-\d{2})|"
    r"(?P<ymd>20\d{2}/\d{2}/\d{2})|"
    r"(?P<mdy>)(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})|"
    r"(?P<yonly>20\d{2})",
    re.I,
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_dates(text: str) -> list[str]:
    out = []
    for m in DATE_RE.finditer(text or ""):
        if m.group("iso"):
            out.append(m.group("iso"))
        elif m.group("ymd"):
            out.append(m.group("ymd").replace("/", "-"))
        elif m.group("year") and m.group("mon"):
            out.append(f"{m.group('mon')} {m.group('day')} {m.group('year')}")
        elif m.group("yonly"):
            out.append(m.group("yonly"))
    # prefer longer dates first uniqueness
    return list(dict.fromkeys(out))[:5]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--ocr-limit", type=int, default=400)
    args = ap.parse_args()

    events = []
    con = sqlite3.connect(str(DB))
    rows = con.execute(
        "SELECT source_path, dest_path, domain FROM ingest "
        "WHERE domain LIKE '%Medical%' OR domain LIKE '%Navy%' OR domain LIKE '%Family%' "
        "OR source_path LIKE '%Medical%' OR source_path LIKE '%VA%' OR source_path LIKE '%Navy%' "
        "LIMIT ?",
        (args.limit,),
    ).fetchall()
    con.close()

    for src, dest, dom in rows:
        blob = f"{src or ''} {dest or ''}"
        dates = extract_dates(blob)
        if not dates:
            continue
        events.append(
            {
                "date": dates[0],
                "dates_all": dates,
                "domain": dom,
                "source": src,
                "dest": dest,
                "title": Path(src or dest or "x").name[:120],
                "evidence": "path",
            }
        )

    # OCR peeks
    ocr_n = 0
    for root_name in ("Medical-Records", "Navy-Service"):
        root = SILO / root_name
        if not root.is_dir():
            continue
        for ocr in root.rglob("*.ocr.md"):
            if ocr_n >= args.ocr_limit:
                break
            try:
                text = ocr.read_text(encoding="utf-8", errors="replace")[:3000]
            except Exception:
                continue
            dates = extract_dates(text + " " + ocr.name)
            if not dates:
                continue
            events.append(
                {
                    "date": dates[0],
                    "dates_all": dates,
                    "domain": root_name,
                    "source": str(ocr).replace(".ocr.md", ""),
                    "title": ocr.name.replace(".ocr.md", "")[:120],
                    "evidence": "ocr",
                }
            )
            ocr_n += 1

    # sort: iso first-ish
    def sort_key(e):
        d = e["date"]
        if re.match(r"20\d{2}-\d{2}-\d{2}", d):
            return d
        if re.match(r"20\d{2}$", d):
            return d + "-00-00"
        return "9999-" + d

    events_sorted = sorted(events, key=sort_key)

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": utc(),
        "event_count": len(events_sorted),
        "events": events_sorted[:5000],
    }
    (OUT / "life_timeline.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # domain splits
    by_dom: dict[str, list] = defaultdict(list)
    for e in events_sorted:
        by_dom[str(e.get("domain") or "unknown")].append(e)
    for dom, evs in by_dom.items():
        safe = re.sub(r"[^\w\-]+", "_", dom)[:60]
        (OUT / f"timeline_{safe}.json").write_text(
            json.dumps({"domain": dom, "count": len(evs), "events": evs[:2000]}, indent=2),
            encoding="utf-8",
        )

    # vault md sample
    VAULT.mkdir(parents=True, exist_ok=True)
    md = [
        f"# Life timeline harvest — {utc()}",
        "",
        f"**Events:** {len(events_sorted)}",
        "",
        "| Date | Domain | Title | Evidence |",
        "|------|--------|-------|----------|",
    ]
    for e in events_sorted[:80]:
        md.append(
            f"| {e['date']} | {e.get('domain')} | `{e['title'][:50]}` | {e['evidence']} |"
        )
    (VAULT / "life-timeline-latest.md").write_text("\n".join(md), encoding="utf-8")

    print(
        json.dumps(
            {
                "events": len(events_sorted),
                "ocr_events": ocr_n,
                "out": str(OUT / "life_timeline.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
