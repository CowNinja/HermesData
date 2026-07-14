#!/usr/bin/env python3
"""Clear OCR tail: park junk, hard-OCR remaining medical gold."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"D:/HermesData/scripts")
from silo_robust_ocr_ladder import ocr_pdf, tesseract_bin  # type: ignore

OCR_DB = Path(r"D:/HermesData/state/ocr_backlog.sqlite3")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    now = utc()
    con = sqlite3.connect(str(OCR_DB), timeout=60)
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

    targets = [
        p
        for (p,) in con.execute(
            "SELECT path FROM ocr_queue WHERE status IN ('queued','empty','needs_ocr') AND ("
            "path LIKE '%VAMC%' OR path LIKE '%DD2807%' OR path LIKE '%DD2808%' "
            "OR path LIKE '%VA_Lab%' OR path LIKE '%HealtheVet%' OR path LIKE '%HNFS%')"
        )
    ]
    print("hard_targets", len(targets))
    ok = 0
    for p in targets:
        path = Path(p)
        if not path.is_file():
            continue
        try:
            tess = tesseract_bin()
            text, engines = ocr_pdf(path, tess)
            chars = len(text or "")
            if chars:
                Path(str(path) + ".ocr.md").write_text(
                    text, encoding="utf-8", errors="replace"
                )
            st = "ok_text" if chars >= 800 else ("needs_ocr" if chars > 0 else "empty")
            con.execute(
                "UPDATE ocr_queue SET status=?, updated_at=? WHERE path=?",
                (st, now, p),
            )
            print(path.name[:55], st, chars, engines)
            if st == "ok_text":
                ok += 1
        except Exception as e:
            print(path.name[:55], "ERR", type(e).__name__, e)
    con.commit()
    print("hard_ok", ok)
    print("stats", dict(con.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
