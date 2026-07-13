#!/usr/bin/env python3
"""Batch fixity: re-hash dest files and compare to registry sha256.

Raises confidence via digital-preservation style fixity checks (NDSA/LOC).
Default: sample recent N rows. --all is slow — use carefully.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG_DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\registry-fixity-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--status", default="copied")
    ap.add_argument("--domain", default="", help="domain LIKE filter e.g. Medical")
    ap.add_argument("--any-status", action="store_true", help="ignore status filter")
    args = ap.parse_args()

    if not REG_DB.exists():
        print(json.dumps({"error": "no registry"}))
        return 1

    con = sqlite3.connect(str(REG_DB))
    con.row_factory = sqlite3.Row
    # ensure columns
    cols = {r[1] for r in con.execute("PRAGMA table_info(ingest)")}
    if "fixity_ok" not in cols:
        con.execute("ALTER TABLE ingest ADD COLUMN fixity_ok INTEGER")
        con.execute("ALTER TABLE ingest ADD COLUMN fixity_checked_at TEXT")
        con.commit()

    if args.any_status:
        q = "SELECT id, source_path, dest_path, sha256 FROM ingest WHERE dest_path IS NOT NULL AND sha256 IS NOT NULL AND sha256 != ''"
        params = []
    else:
        q = "SELECT id, source_path, dest_path, sha256 FROM ingest WHERE status=? AND dest_path IS NOT NULL AND sha256 IS NOT NULL AND sha256 != ''"
        params = [args.status]
    if args.domain:
        q += " AND domain LIKE ?"
        params.append(f"%{args.domain}%")
    # prefer unchecked
    q += " AND (fixity_ok IS NULL OR fixity_ok = 0) ORDER BY CASE WHEN fixity_ok = 0 THEN 0 ELSE 1 END, id DESC LIMIT ?"
    params.append(args.limit)
    rows = con.execute(q, tuple(params)).fetchall()

    ok = bad = missing = 0
    bad_rows = []
    for r in rows:
        dest = Path(r["dest_path"])
        if not dest.is_file():
            missing += 1
            con.execute(
                "UPDATE ingest SET fixity_ok=0, fixity_checked_at=? WHERE id=?",
                (utc(), r["id"]),
            )
            bad_rows.append((r["dest_path"], "missing_dest"))
            continue
        try:
            dig = sha256_file(dest)
        except Exception as e:
            bad += 1
            bad_rows.append((r["dest_path"], str(e)[:80]))
            continue
        if dig.lower() == (r["sha256"] or "").lower():
            ok += 1
            con.execute(
                "UPDATE ingest SET fixity_ok=1, fixity_checked_at=?, status=? WHERE id=?",
                (utc(), "verified" if r["id"] else "verified", r["id"]),
            )
            # only set verified if was copied
            con.execute(
                "UPDATE ingest SET status='verified' WHERE id=? AND status='copied'",
                (r["id"],),
            )
        else:
            bad += 1
            con.execute(
                "UPDATE ingest SET fixity_ok=0, fixity_checked_at=? WHERE id=?",
                (utc(), r["id"]),
            )
            bad_rows.append((r["dest_path"], "hash_mismatch"))
    con.commit()
    con.close()

    lines = [
        f"# Registry fixity batch — {utc()}",
        "",
        f"checked={len(rows)} **ok={ok}** bad={bad} missing={missing}",
        "",
        "## Failures",
        "",
    ]
    if not bad_rows:
        lines.append("_None_")
    else:
        for path, err in bad_rows[:40]:
            lines.append(f"- `{Path(path).name[:60]}` — {err}")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "checked": len(rows),
                "ok": ok,
                "bad": bad,
                "missing": missing,
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0 if bad == 0 and missing == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
