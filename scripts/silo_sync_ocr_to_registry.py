#!/usr/bin/env python3
"""Sync OCR ok_text outcomes into ingest_registry process_status.

Closes the loop: land -> OCR -> registry shelf label (extracted).
Fast path: indexed dest_path exact + slash-flip (idx_ingest_dest).
Slow path: basename LIKE only for unmatched remainder (capped).

Mirrors silo_sync_stt_to_registry semantics; never downgrades
extracted / derivative_ok / context_enriched.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

OCR = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-sync-ocr-registry-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def variants(path: str) -> list[str]:
    raw = (path or "").strip()
    if not raw:
        return []
    n = raw.replace("/", "\\")
    while "\\\\" in n:
        n = n.replace("\\\\", "\\")
    out = []
    seen: set[str] = set()
    for c in (raw, n, n.replace("\\", "/"), raw.replace("\\", "/"), raw.replace("/", "\\")):
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args()
    if not OCR.is_file() or not REG.is_file():
        print(json.dumps({"error": "db missing"}))
        return 2

    oc = sqlite3.connect(str(OCR), timeout=120)
    rg = sqlite3.connect(str(REG), timeout=120)
    for db in (oc, rg):
        try:
            db.execute("PRAGMA busy_timeout=120000")
        except Exception:
            pass

    # detect optional columns
    cols = {r[1] for r in rg.execute("PRAGMA table_info(ingest)").fetchall()}
    has_notes = "notes" in cols
    has_last = "last_seen" in cols

    mapping = {
        "ok_text": "extracted",
        "encrypted": "encrypted",
        "corrupt_retired": "ocr_failed",
        "missing": "missing_dest",
        "empty": "ocr_empty",
        "archive_skip": "catalog_only",
        "thin_image": "catalog_only",
        "image_sparse": "catalog_only",
        "needs_ocr": "ocr_queued",
        "queued": "ocr_queued",
        "error": "ocr_queued",
    }
    # promote success first
    order = [
        "ok_text",
        "encrypted",
        "corrupt_retired",
        "missing",
        "empty",
        "archive_skip",
        "thin_image",
        "image_sparse",
        "needs_ocr",
        "queued",
        "error",
    ]

    updated = 0
    matched = 0
    unmatched = 0
    exact_hits = 0
    like_hits = 0
    samples: list[dict] = []
    unmatched_samples: list[str] = []
    terminal_ok = {"extracted", "derivative_ok", "context_enriched"}

    # cache: path-variant -> (rowid, process_status, dest)
    cache: dict[str, tuple | None] = {}

    def find_row(path: str):
        nonlocal exact_hits, like_hits
        for c in variants(path):
            if c in cache:
                if cache[c] is not None:
                    return cache[c]
                continue
            cur = rg.execute(
                "SELECT rowid, process_status, dest_path FROM ingest WHERE dest_path=? LIMIT 1",
                (c,),
            ).fetchone()
            cache[c] = cur
            if cur:
                exact_hits += 1
                return cur
        # one basename LIKE fallback
        name = Path(path).name
        if name and len(name) >= 8:
            cur = rg.execute(
                "SELECT rowid, process_status, dest_path FROM ingest WHERE dest_path LIKE ? LIMIT 1",
                ("%" + name,),
            ).fetchone()
            if cur:
                like_hits += 1
                cache[path] = cur
                return cur
        cache[path] = None
        return None

    for ostatus in order:
        pstatus = mapping[ostatus]
        rows = oc.execute(
            "SELECT path, chars, engine FROM ocr_queue WHERE status=? LIMIT ?",
            (ostatus, args.limit),
        ).fetchall()
        for path, chars, engine in rows:
            cur = find_row(path)
            if not cur:
                unmatched += 1
                if len(unmatched_samples) < 6:
                    unmatched_samples.append(str(path)[:160])
                continue
            matched += 1
            rowid, old, dest = cur
            if old == pstatus:
                continue
            if old in terminal_ok and pstatus != "extracted":
                continue
            if old == "derivative_ok":
                continue
            note = f" | ocr_sync:{ostatus}:{engine or ''}:chars={chars or 0}"
            if has_notes and has_last:
                rg.execute(
                    "UPDATE ingest SET process_status=?, last_seen=?, notes=COALESCE(notes,'') || ? WHERE rowid=?",
                    (pstatus, utc(), note, rowid),
                )
            elif has_last:
                rg.execute(
                    "UPDATE ingest SET process_status=?, last_seen=? WHERE rowid=?",
                    (pstatus, utc(), rowid),
                )
            else:
                rg.execute(
                    "UPDATE ingest SET process_status=? WHERE rowid=?",
                    (pstatus, rowid),
                )
            updated += 1
            if len(samples) < 8:
                samples.append(
                    {
                        "path": Path(path).name,
                        "old": old,
                        "new": pstatus,
                        "chars": chars,
                        "dest": (dest or "")[-80:],
                    }
                )
            if updated >= args.limit:
                break
        if updated >= args.limit:
            break

    rg.commit()
    by = dict(
        rg.execute(
            "SELECT process_status, COUNT(*) FROM ingest GROUP BY process_status"
        ).fetchall()
    )
    oc.close()
    rg.close()
    out = {
        "updated": updated,
        "matched": matched,
        "unmatched": unmatched,
        "exact_hits": exact_hits,
        "like_hits": like_hits,
        "unmatched_samples": unmatched_samples,
        "by_process": by,
        "samples": samples,
        "at": utc(),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"# OCR→registry sync — {utc()}\n\n```json\n{json.dumps(out, indent=2)[:5000]}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(out, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
