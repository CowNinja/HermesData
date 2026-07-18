#!/usr/bin/env python3
"""Print exactly six ground-truth silo numbers (Discord-safe, no prose).

Hermes data-silo lane MUST run this (or scoreboard_pulse) before any metrics claim.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_registry import connect, stats  # noqa: E402


def main() -> int:
    con = connect()
    s = stats(con)
    con.close()
    by_st = {r["status"]: r["c"] for r in s.get("by_status") or []}
    by_pr = {r["process_status"]: r["c"] for r in s.get("by_process") or []}
    ok_text = 0
    ocr_open = 0
    try:
        oc = sqlite3.connect(r"D:\HermesData\state\ocr_backlog.sqlite3", timeout=30)
        for st, n in oc.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"):
            if st == "ok_text":
                ok_text = int(n)
            if st in ("needs_ocr", "queued", "error"):
                ocr_open += int(n)
        oc.close()
    except Exception:
        ok_text = -1
        ocr_open = -1

    nums = {
        "1_registry_total": int(s.get("total_ingest_rows") or 0),
        "2_unique_hashes": int(s.get("unique_hashes") or 0),
        "3_status_copied": int(by_st.get("copied") or 0),
        "4_status_landed": int(by_st.get("landed") or 0),
        "5_ocr_ok_text": int(ok_text),
        "6_ocr_open": int(ocr_open),
        "bonus_unprocessed": int(by_pr.get("unprocessed") or 0),
        "bonus_derivative_ok": int(by_pr.get("derivative_ok") or 0),
    }
    # Human + machine
    print("SILO_SIX_NUMBERS")
    print(f"1 registry_total={nums['1_registry_total']}")
    print(f"2 unique_hashes={nums['2_unique_hashes']}")
    print(f"3 status_copied={nums['3_status_copied']}")
    print(f"4 status_landed={nums['4_status_landed']}")
    print(f"5 ocr_ok_text={nums['5_ocr_ok_text']}")
    print(f"6 ocr_open={nums['6_ocr_open']}")
    print("JSON " + json.dumps(nums, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
