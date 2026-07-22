#!/usr/bin/env python3
"""Mark/repoint unprocessed registry rows whose dest_path is missing (ghosts).

Catalog hygiene only — does not delete files or restart gateway.
Policy:
  1) If sha256 has another live dest_path → repoint dest+domain
  2) Else mark process_status=ghost_cleared (idempotent)

Research basis: post-land registry truth; missing dest ≠ OCR work
(Karpathy wiki: raw immutable, don't thrash compiled layer on ghosts).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-ghost-clear-latest.md")
JSON = Path(r"D:/HermesData/state/silo_ghost_clear_latest.json")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(ingest)").fetchall()}
    if "process_status" not in cols:
        con.execute(
            "ALTER TABLE ingest ADD COLUMN process_status TEXT DEFAULT 'unprocessed'"
        )
        con.commit()

    id_col = "id" if "id" in cols else "rowid"
    # Prefer unprocessed with dest set
    q = f"""SELECT {id_col} AS rid, dest_path, sha256, domain, process_status
            FROM ingest
            WHERE dest_path IS NOT NULL AND dest_path != ''
              AND (process_status IS NULL OR process_status='unprocessed')
            LIMIT ?"""
    rows = con.execute(q, (args.limit,)).fetchall()

    scanned = 0
    missing = 0
    repointed = 0
    cleared = 0
    live = 0
    examples = {"repointed": [], "cleared": []}

    for r in rows:
        scanned += 1
        dest = r["dest_path"]
        try:
            if Path(dest).is_file():
                live += 1
                continue
        except Exception:
            pass
        missing += 1
        rid = r["rid"]
        sha = r["sha256"]
        new_dest = None
        new_dom = None
        if sha:
            alt = con.execute(
                """SELECT dest_path, domain FROM ingest
                   WHERE sha256=? AND dest_path IS NOT NULL AND dest_path != ?
                   LIMIT 8""",
                (sha, dest),
            ).fetchall()
            for a in alt:
                try:
                    if Path(a[0]).is_file():
                        new_dest, new_dom = a[0], a[1]
                        break
                except Exception:
                    continue
        if new_dest:
            if not args.dry_run:
                try:
                    con.execute(
                        f"UPDATE ingest SET dest_path=?, domain=COALESCE(?, domain), process_status=COALESCE(process_status,'unprocessed') WHERE {id_col}=?",
                        (new_dest, new_dom, rid),
                    )
                    repointed += 1
                    if len(examples["repointed"]) < 5:
                        examples["repointed"].append(
                            {"from": dest[:120], "to": new_dest[:120], "domain": new_dom}
                        )
                except sqlite3.IntegrityError:
                    # UNIQUE(source_path, dest_path) collision — mark cleared instead
                    con.execute(
                        f"UPDATE ingest SET process_status='ghost_cleared' WHERE {id_col}=?",
                        (rid,),
                    )
                    cleared += 1
                    if len(examples["cleared"]) < 5:
                        examples["cleared"].append(f"collision:{dest[:120]}")
            else:
                repointed += 1
                if len(examples["repointed"]) < 5:
                    examples["repointed"].append(
                        {"from": dest[:120], "to": new_dest[:120], "domain": new_dom}
                    )
        else:
            if not args.dry_run:
                con.execute(
                    f"UPDATE ingest SET process_status='ghost_cleared' WHERE {id_col}=?",
                    (rid,),
                )
            cleared += 1
            if len(examples["cleared"]) < 5:
                examples["cleared"].append(dest[:140])

    if not args.dry_run:
        con.commit()

    by = dict(
        con.execute(
            "SELECT COALESCE(process_status,'null'), COUNT(*) FROM ingest GROUP BY 1"
        ).fetchall()
    )
    con.close()

    payload = {
        "at": utc(),
        "dry_run": args.dry_run,
        "limit": args.limit,
        "scanned": scanned,
        "live_ok": live,
        "missing": missing,
        "repointed": repointed,
        "ghost_cleared": cleared,
        "by_process": by,
        "examples": examples,
    }
    JSON.parent.mkdir(parents=True, exist_ok=True)
    JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Ghost clear — {payload['at']}",
        "",
        f"**Mode:** {'DRY-RUN' if args.dry_run else 'LIVE'} · limit={args.limit}",
        "",
        f"| Metric | N |",
        f"|--------|--:|",
        f"| scanned | {scanned} |",
        f"| live_ok | {live} |",
        f"| missing | {missing} |",
        f"| repointed | {repointed} |",
        f"| ghost_cleared | {cleared} |",
        "",
        "Policy: missing dest + live sha twin → repoint; else `ghost_cleared`. No deletes.",
        "",
        f"JSON: `{JSON}`",
        "",
        "[[Operations/logs/silo-unprocessed-triage-latest]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in payload if k != "examples"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
