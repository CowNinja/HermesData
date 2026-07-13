#!/usr/bin/env python3
"""Clean OCR/extract text into denser twin/RAG training sidecars (.train.md).

- Reads .ocr.md or .extract.json next to Medical/Navy files
- Strips fence noise, repeated headers, form-feed junk
- Writes/updates .train.md when clean text is useful
- Safe, incremental, no source mutation

Usage:
  python silo_ocr_text_clean.py --limit 40
  python silo_ocr_text_clean.py --limit 40 --domain Navy
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

OCR_DB = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-ocr-text-clean-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(raw: str) -> str:
    t = raw or ""
    # drop markdown wrapper from our ocr.md format
    if "```" in t:
        parts = t.split("```")
        # take longest fenced or body chunk
        chunks = [p for p in parts if len(p.strip()) > 40]
        if chunks:
            t = max(chunks, key=len)
    # strip our header lines
    lines = []
    for line in t.splitlines():
        if re.match(r"^#\s*OCR/", line):
            continue
        if re.match(r"^-\s*(at|status|engine|chars|reason):", line):
            continue
        lines.append(line)
    t = "\n".join(lines)
    t = t.replace("\x0c", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # drop lines that are mostly garbage symbols
    kept = []
    for line in t.splitlines():
        s = line.strip()
        if not s:
            kept.append("")
            continue
        alnum = sum(c.isalnum() for c in s)
        if len(s) >= 4 and alnum / max(len(s), 1) < 0.25:
            continue
        kept.append(line)
    t = "\n".join(kept)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def extract_from_ocr_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--domain", default="", help="Medical or Navy filter on path")
    ap.add_argument("--min-chars", type=int, default=200)
    args = ap.parse_args()

    if not OCR_DB.exists():
        print(json.dumps({"error": "no ocr db"}))
        return 1

    con = sqlite3.connect(str(OCR_DB), timeout=60)
    q = "SELECT path, chars FROM ocr_queue WHERE status='ok_text' AND IFNULL(chars,0) >= ? ORDER BY chars DESC LIMIT ?"
    params: list = [args.min_chars, args.limit * 3]
    rows = con.execute(q, params).fetchall()
    con.close()

    if args.domain:
        rows = [r for r in rows if args.domain.lower() in (r[0] or "").lower()]
    rows = rows[: args.limit]

    written = 0
    skipped = 0
    samples = []
    for path_s, chars in rows:
        p = Path(path_s)
        ocr = Path(str(p) + ".ocr.md")
        if not ocr.is_file():
            skipped += 1
            continue
        raw = extract_from_ocr_md(ocr)
        cleaned = clean_text(raw)
        if len(cleaned) < args.min_chars:
            skipped += 1
            continue
        train = Path(str(p) + ".train.md")
        # don't shrink a better train
        if train.is_file() and train.stat().st_size > len(cleaned) + 200:
            skipped += 1
            continue
        body = (
            f"# Train extract — {p.name}\n\n"
            f"source: silo_ocr_text_clean\n"
            f"cleaned_at: {utc()}\n"
            f"chars: {len(cleaned)}\n\n"
            f"{cleaned[:12000]}\n"
        )
        train.write_text(body, encoding="utf-8")
        written += 1
        samples.append({"file": p.name, "chars": len(cleaned)})
        # bump registry if unprocessed
        try:
            rcon = sqlite3.connect(str(REG), timeout=30)
            rcon.execute(
                """UPDATE ingest SET process_status='derivative_ok', last_seen=?
                   WHERE dest_path=? AND process_status IN ('unprocessed','extracted')""",
                (utc(), str(p)),
            )
            rcon.commit()
            rcon.close()
        except Exception:
            pass

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# OCR text clean — {utc()}",
        "",
        f"written **{written}** · skipped **{skipped}** · domain `{args.domain or 'any'}`",
        "",
    ]
    for s in samples[:20]:
        lines.append(f"- {s['chars']} chars `{s['file']}`")
    lines += ["", "[[Operations/Post-Ingest-QA-Repair-Enrichment-CANONICAL-2026-07-13]]", ""]
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "written": written,
                "skipped": skipped,
                "samples": samples[:10],
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
