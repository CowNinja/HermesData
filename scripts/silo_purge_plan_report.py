#!/usr/bin/env python3
"""Read-only purge plan report — NEVER deletes.

Gates mirror Operations/Purge-Plan-Prep-CANONICAL-2026-07-14.md.
Not armed until Jeff exact phrase: purge drive OK
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
OCR = Path(r"D:/HermesData/state/ocr_backlog.sqlite3")
OUT = Path(r"D:/PhronesisVault/Operations/logs/silo-purge-plan-report-latest.md")
CANON = "Operations/Purge-Plan-Prep-CANONICAL-2026-07-14"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    con = sqlite3.connect(str(REG), timeout=60)
    total = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    with_dest = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE dest_path IS NOT NULL AND dest_path!=''"
    ).fetchone()[0]
    try:
        bb = con.execute(
            "SELECT COUNT(*) FROM ingest WHERE process_status='landed_booksbloom_pilot'"
        ).fetchone()[0]
    except Exception:
        bb = -1
    ok = miss = 0
    miss_samples: list[str] = []
    for (dest,) in con.execute(
        "SELECT dest_path FROM ingest WHERE dest_path IS NOT NULL ORDER BY RANDOM() LIMIT 50"
    ):
        if dest and Path(dest).is_file():
            ok += 1
        else:
            miss += 1
            if dest and len(miss_samples) < 5:
                miss_samples.append(str(dest)[:160])
    # open OCR gold (blocks gate 4)
    open_ocr = gold_open = 0
    ocr_stats: dict = {}
    if OCR.is_file():
        oc = sqlite3.connect(str(OCR), timeout=30)
        ocr_stats = dict(oc.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"))
        open_ocr = (
            ocr_stats.get("needs_ocr", 0)
            + ocr_stats.get("queued", 0)
            + ocr_stats.get("error", 0)
        )
        gold_open = oc.execute(
            """SELECT COUNT(*) FROM ocr_queue
               WHERE status IN ('needs_ocr','queued','error')
                 AND (score >= 500 OR path LIKE '%DD280%' OR path LIKE '%VAMC%'
                      OR path LIKE '%Medical%' OR path LIKE '%Navy%')"""
        ).fetchone()[0]
        oc.close()

    gate_dest = ok >= 45  # 90% of 50-sample
    gate_ocr_gold = gold_open == 0
    gate_bb = bb >= 0  # present
    all_ready = gate_dest and gate_ocr_gold and with_dest == total
    now = utc()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    miss_md = "\n".join(f"- `{m}`" for m in miss_samples) or "- _(none)_"
    OUT.write_text(
        f"""# Purge plan report (READ-ONLY) — {now}

**NOT ARMED. No deletions.** Phrase required: `purge drive OK`

## Spot checks

| Check | Value | Gate |
|-------|------:|:----:|
| Registry total | {total} | — |
| With dest_path | {with_dest} | {"✅" if with_dest == total else "⚠️"} |
| Spot dest exists (50) | {ok}/{ok+miss} | {"✅" if gate_dest else "⚠️"} |
| Booksbloom pilot landed | {bb} | {"✅" if gate_bb else "—"} |
| OCR open (needs/queued/error) | {open_ocr} | — |
| OCR open **gold** | {gold_open} | {"✅" if gate_ocr_gold else "🚫"} |
| Jeff green light | required | 🚫 until phrase |

## OCR status snapshot
`{json.dumps(ocr_stats)}`

## Miss samples (dest not on disk)
{miss_md}

## Ready for Jeff review?
**{"YES — all automated gates green (still need phrase)" if all_ready else "NO — fix dest/OCR gold first"}**

See [[{CANON}]]
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "total": total,
                "dest_ok_sample": ok,
                "dest_miss_sample": miss,
                "booksbloom": bb,
                "ocr_open": open_ocr,
                "ocr_gold_open": gold_open,
                "ready_for_phrase": all_ready,
                "receipt": str(OUT),
            }
        )
    )
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
