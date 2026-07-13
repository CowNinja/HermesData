#!/usr/bin/env python3
"""Post-ingest repair: re-pull from G:/source when dest missing, zero real-bytes, or fixity fail.

Safe: copy2 only; never deletes source. Skips Google Drive stubs (.gdoc/.gsheet) as provenance.
Medical/Navy priority.

Usage:
  python silo_repair_re_pull.py --limit 40
  python silo_repair_re_pull.py --apply --limit 40
  python silo_repair_re_pull.py --apply --domain Medical --limit 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-repair-re-pull-latest.md")
STUB_EXT = {".gdoc", ".gsheet", ".gslides", ".gdraw", ".gform", ".gtable"}


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


def is_stub(path: Path) -> bool:
    return path.suffix.lower() in STUB_EXT


def candidates(con: sqlite3.Connection, domain: str, limit: int) -> List[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    dom = f"%{domain}%" if domain else "%"
    # priority: fixity fail, missing-ish, zero size non-stub
    rows = con.execute(
        """
        SELECT id, source_path, dest_path, sha256, size, domain, fixity_ok, process_status
        FROM ingest
        WHERE domain LIKE ?
          AND source_path IS NOT NULL AND source_path != ''
          AND (
            fixity_ok = 0
            OR IFNULL(size, 0) = 0
          )
        ORDER BY
          CASE WHEN fixity_ok = 0 THEN 0 ELSE 1 END,
          CASE WHEN domain LIKE '%Medical%' THEN 0 WHEN domain LIKE '%Navy%' THEN 1 ELSE 2 END,
          id ASC
        LIMIT ?
        """,
        (dom, limit * 3),
    ).fetchall()
    out = []
    for r in rows:
        dest = Path(r["dest_path"] or "")
        if is_stub(dest):
            continue
        # include if missing dest, zero size, or fixity fail
        missing = not dest.is_file()
        zero = (r["size"] or 0) == 0 or (dest.is_file() and dest.stat().st_size == 0)
        fail = r["fixity_ok"] == 0
        if missing or zero or fail:
            out.append(r)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--domain", default="", help="substring e.g. Medical or Navy")
    args = ap.parse_args()

    con = sqlite3.connect(str(REG), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    rows = candidates(con, args.domain, args.limit)

    stats = {
        "planned": len(rows),
        "re_pulled": 0,
        "hash_ok_after": 0,
        "src_missing": 0,
        "stub_skipped_prefilter": 0,
        "errors": 0,
        "marked_stub_zero": 0,
    }
    details: List[Dict[str, Any]] = []

    # also mark remaining zero-byte stubs in domain as provenance (notes only)
    if args.apply:
        stub_rows = con.execute(
            """
            SELECT id, dest_path FROM ingest
            WHERE domain LIKE ? AND IFNULL(size,0)=0
            LIMIT 200
            """,
            (f"%{args.domain}%" if args.domain else "%",),
        ).fetchall()
        for sid, dpath in stub_rows:
            p = Path(dpath or "")
            if is_stub(p):
                con.execute(
                    """UPDATE ingest SET process_status=COALESCE(process_status,'unprocessed'),
                       notes=COALESCE(notes,'') || ' | provenance_stub_google_zero_byte',
                       last_seen=? WHERE id=?""",
                    (utc(), sid),
                )
                stats["marked_stub_zero"] += 1

    for r in rows:
        src = Path(r["source_path"])
        dest = Path(r["dest_path"])
        rec: Dict[str, Any] = {
            "id": r["id"],
            "dest": str(dest),
            "domain": r["domain"],
            "reason": [],
        }
        if not dest.is_file():
            rec["reason"].append("missing_dest")
        if (r["size"] or 0) == 0:
            rec["reason"].append("zero_size")
        if r["fixity_ok"] == 0:
            rec["reason"].append("fixity_fail")

        if not src.is_file():
            stats["src_missing"] += 1
            rec["status"] = "src_missing"
            details.append(rec)
            continue

        if not args.apply:
            rec["status"] = "would_re_pull"
            details.append(rec)
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            dig = sha256_file(dest)
            size = dest.stat().st_size
            # Source re-pull is authoritative for bytes on K
            fix_ok = 1
            con.execute(
                """UPDATE ingest SET dest_path=?, size=?, sha256=?, fixity_ok=1,
                   fixity_checked_at=?, last_seen=?,
                   notes=COALESCE(notes,'') || ' | re_pulled_source_authoritative'
                   WHERE id=?""",
                (str(dest), size, dig, utc(), utc(), r["id"]),
            )
            stats["re_pulled"] += 1
            if fix_ok:
                stats["hash_ok_after"] += 1
            rec["status"] = "re_pulled"
            rec["size"] = size
            rec["fixity_ok"] = fix_ok
        except Exception as e:
            stats["errors"] += 1
            rec["status"] = f"error:{e}"[:120]
        details.append(rec)

    if args.apply:
        con.commit()
    con.close()

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Silo repair re-pull — {utc()}",
        "",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'} · domain `{args.domain or 'all'}`",
        f"**Planned:** {stats['planned']} · **re_pulled:** {stats['re_pulled']} · **hash_ok:** {stats['hash_ok_after']} · **src_missing:** {stats['src_missing']} · **errors:** {stats['errors']}",
        f"**Stub zeros marked:** {stats['marked_stub_zero']}",
        "",
        "| Status | Domain | Reasons | File |",
        "|--------|--------|---------|------|",
    ]
    for d in details[:40]:
        lines.append(
            f"| {d.get('status')} | {d.get('domain')} | {','.join(d.get('reason') or [])} | `{Path(d.get('dest') or '').name[:50]}` |"
        )
    lines += ["", "[[Operations/Post-Ingest-QA-Repair-Enrichment-CANONICAL-2026-07-13]]", ""]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"apply": args.apply, **stats, "receipt": str(RECEIPT), "sample": details[:8]}, indent=2))
    return 0 if stats["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
