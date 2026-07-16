#!/usr/bin/env python3
"""Clear OCR tail: park junk, promote fat sidecars, hard-OCR remaining medical gold.

Hang-prevention (2026-07-14):
- Worker used attempts < 4 so gold DD2807/2808 with attempts 5–6 were never reselected.
- Fat .ocr.md could exist while queue still said needs_ocr/chars=0.
This script always: park chrome → promote fat → force-process remaining open gold.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"D:/HermesData/scripts")
from silo_robust_ocr_ladder import process_one, tesseract_bin  # type: ignore

OCR_DB = Path(r"D:/HermesData/state/ocr_backlog.sqlite3")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def promote_fat(con: sqlite3.Connection, now: str) -> int:
    n = 0
    for path, st in list(
        con.execute(
            "SELECT path, status FROM ocr_queue WHERE status IN ('needs_ocr','empty','error')"
        )
    ):
        ocr = Path(str(path) + ".ocr.md")
        if ocr.is_file() and ocr.stat().st_size >= 800:
            try:
                chars = len(ocr.read_text(encoding="utf-8", errors="replace").strip())
            except Exception:
                chars = int(ocr.stat().st_size)
            con.execute(
                "UPDATE ocr_queue SET status='ok_text', chars=?, engine=COALESCE(NULLIF(engine,''), 'promote_fat'), updated_at=? WHERE path=?",
                (chars, now, path),
            )
            n += 1
    con.commit()
    return n


def main() -> int:
    now = utc()
    con = sqlite3.connect(str(OCR_DB), timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
    except Exception:
        pass
    parked = 0
    for path, st in list(
        con.execute(
            "SELECT path,status FROM ocr_queue WHERE status IN ('empty','queued','needs_ocr')"
        )
    ):
        name = Path(path).name.lower()
        low = path.lower().replace("\\", "/")
        if name in (
            "address.png",
            "pagebackground.png",
            "pagefooter.png",
            "pagetop.png",
            "phone.png",
        ) or ("/images/" in low and name.endswith(".png")):
            con.execute(
                "UPDATE ocr_queue SET status='archive_skip', score=1, updated_at=? WHERE path=?",
                (now, path),
            )
            parked += 1
    con.commit()
    print("parked", parked)

    promoted = promote_fat(con, now)
    print("promoted_fat", promoted)

    targets = [
        p
        for (p,) in con.execute(
            "SELECT path FROM ocr_queue WHERE status IN ('queued','empty','needs_ocr','error') AND ("
            "path LIKE '%VAMC%' OR path LIKE '%DD2807%' OR path LIKE '%DD2808%' "
            "OR path LIKE '%VA_Lab%' OR path LIKE '%HealtheVet%' OR path LIKE '%HNFS%' "
            "OR path LIKE '%Medical%' OR path LIKE '%SHPE%' OR score >= 500)"
        )
    ]
    # also any remaining open high-value
    extra = [
        p
        for (p,) in con.execute(
            "SELECT path FROM ocr_queue WHERE status IN ('queued','empty','needs_ocr') ORDER BY score DESC LIMIT 20"
        )
    ]
    seen = set(targets)
    for p in extra:
        if p not in seen:
            targets.append(p)
            seen.add(p)
    print("hard_targets", len(targets))
    ok = 0
    tess = tesseract_bin()
    for p in targets:
        path = Path(p)
        if not path.is_file():
            con.execute(
                "UPDATE ocr_queue SET status='missing', updated_at=? WHERE path=?",
                (now, p),
            )
            continue
        try:
            # Medical multipage: more pages + short-temp copy inside ladder
            rec = process_one(path, tess, True, 16)
            q = rec.get("quality") or {}
            chars = int(q.get("chars") or 0)
            engine = rec.get("engine") or "hard_tail"
            st = "ok_text" if chars >= 800 or q.get("status") == "ok_text" else (
                "needs_ocr" if chars > 0 else "empty"
            )
            # fat sidecar race
            ocr_side = Path(str(path) + ".ocr.md")
            if st != "ok_text" and ocr_side.is_file() and ocr_side.stat().st_size >= 800:
                st = "ok_text"
                if chars < 800:
                    chars = len(ocr_side.read_text(encoding="utf-8", errors="replace").strip())
            con.execute(
                "UPDATE ocr_queue SET status=?, chars=?, engine=?, updated_at=?, attempts=attempts+1 WHERE path=?",
                (st, chars, engine, now, p),
            )
            print(path.name[:55], st, chars, engine)
            if st == "ok_text":
                ok += 1
        except Exception as e:
            print(path.name[:55], "ERR", type(e).__name__, e)
            con.execute(
                "UPDATE ocr_queue SET status='error', updated_at=?, attempts=attempts+1 WHERE path=?",
                (now, p),
            )
    con.commit()
    print("hard_ok", ok)
    print("stats", dict(con.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status")))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
