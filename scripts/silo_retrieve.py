#!/usr/bin/env python3
"""Catalog-first document retrieval for the Personal Digital Silo.

Usage:
  python silo_retrieve.py "richardson endo 2018"
  python silo_retrieve.py --domain Medical-Records cpap
  python silo_retrieve.py --limit 10 wounded warrior
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import List

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
FUSED = Path(r"D:\HermesData\state\fused_index.sqlite3")


def tokens(q: str) -> List[str]:
    return [t for t in re.split(r"\s+", q.strip().lower()) if len(t) >= 2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="+", help="search words")
    ap.add_argument("--domain", default="", help="optional domain filter substring")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--include-inbox", action="store_true")
    args = ap.parse_args()
    q = " ".join(args.query)
    toks = tokens(q)
    if not toks:
        print(json.dumps({"error": "empty query"}))
        return 1
    if not DB.exists():
        print(json.dumps({"error": "no registry"}))
        return 1

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    # progressive filter: all tokens must appear in dest_path or source_path
    sql = "SELECT domain, dest_path, source_path, size, process_status, sha256 FROM ingest WHERE 1=1"
    params: list = []
    if args.domain:
        sql += " AND domain LIKE ?"
        params.append(f"%{args.domain}%")
    if not args.include_inbox:
        sql += " AND domain NOT LIKE '%_Inbox%'"
    for t in toks:
        sql += " AND (lower(dest_path) LIKE ? OR lower(IFNULL(source_path,'')) LIKE ?)"
        params.extend([f"%{t}%", f"%{t}%"])
    sql += " ORDER BY CASE process_status WHEN 'derivative_ok' THEN 0 WHEN 'extracted' THEN 1 WHEN 'context_enriched' THEN 2 ELSE 3 END, size DESC LIMIT ?"
    params.append(args.limit * 3)  # fetch extra then dedupe by sha
    rows = con.execute(sql, params).fetchall()
    con.close()

    seen = set()
    hits = []
    for r in rows:
        sha = r["sha256"] or r["dest_path"]
        if sha in seen:
            continue
        seen.add(sha)
        hits.append(
            {
                "domain": r["domain"],
                "path": r["dest_path"],
                "size": r["size"],
                "process_status": r["process_status"],
                "sha16": (r["sha256"] or "")[:16],
            }
        )
        if len(hits) >= args.limit:
            break

    fused_note = None
    if FUSED.exists() and hits:
        try:
            fcon = sqlite3.connect(str(FUSED))
            for h in hits:
                if not h["sha16"]:
                    continue
                fr = fcon.execute(
                    "SELECT cluster_id, card_path, member_count, train_value FROM fused_exact WHERE sha256 LIKE ?",
                    (h["sha16"] + "%",),
                ).fetchone()
                if fr:
                    h["fused_card"] = fr[1]
                    h["fused_members"] = fr[2]
                    h["train_value"] = fr[3]
            fcon.close()
        except Exception as e:
            fused_note = str(e)

    print(
        json.dumps(
            {
                "query": q,
                "tokens": toks,
                "domain_filter": args.domain or None,
                "hits": hits,
                "count": len(hits),
                "fused_note": fused_note,
                "tip": "Catalog-first. Nested origin path preserved on disk.",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
