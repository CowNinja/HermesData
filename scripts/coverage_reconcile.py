#!/usr/bin/env python3
"""Reconcile MemoryCard GD source file counts vs ingest registry coverage.

Confidence booster: know how much of the tree is tracked (path or hash).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\coverage-reconcile-latest.md")

ROOTS = [
    Path(r"G:\MemoryCard_Backups\Google Drive"),
    Path(r"G:\MemoryCard_Backups\Google Drive(archive)"),
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-scan", type=int, default=80_000)
    args = ap.parse_args()

    skip: set[str] = set()
    hash_n = rows_n = 0
    if REG.exists():
        con = sqlite3.connect(str(REG))
        rows_n = con.execute("select count(*) from ingest").fetchone()[0]
        for (sp,) in con.execute("select source_path from ingest"):
            if sp:
                skip.add(sp)
        try:
            hash_n = con.execute("select count(distinct sha256) from hash_seen").fetchone()[0]
        except Exception:
            hash_n = con.execute(
                "select count(distinct sha256) from ingest where sha256 is not null"
            ).fetchone()[0]
        con.close()

    scanned = tracked = untracked = 0
    samples = []
    for root in ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if scanned >= args.max_scan:
                break
            if not p.is_file():
                continue
            if p.name.startswith(".") or p.name.endswith(".meta.json"):
                continue
            if p.name.lower() in {"desktop.ini", "thumbs.db"}:
                continue
            scanned += 1
            sp = str(p)
            if sp in skip:
                tracked += 1
            else:
                untracked += 1
                if len(samples) < 8:
                    samples.append(sp)
        if scanned >= args.max_scan:
            break

    pct = (100.0 * tracked / scanned) if scanned else 0.0
    lines = [
        f"# Coverage reconcile — {utc()}",
        "",
        f"scanned={scanned} tracked_path={tracked} untracked={untracked} **path_coverage={pct:.1f}%**",
        f"registry_rows={rows_n} unique_hashes≈{hash_n}",
        "",
        "## Sample untracked",
        "",
    ]
    for s in samples:
        lines.append(f"- `{s[:120]}`")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "scanned": scanned,
                "tracked": tracked,
                "untracked": untracked,
                "path_coverage_pct": round(pct, 2),
                "registry_rows": rows_n,
                "unique_hashes": hash_n,
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
