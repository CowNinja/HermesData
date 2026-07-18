#!/usr/bin/env python3
"""Unprocessed triage — bucket sample for depth planning (no OCR thrash)."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
OUT = Path(r"D:/PhronesisVault/Operations/logs/silo-unprocessed-triage-latest.md")
JSON = Path(r"D:/HermesData/state/silo_unprocessed_triage_latest.json")

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".eml", ".rtf", ".xml", ".log", ".yaml", ".yml"}
IMG = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".heic"}
AV = {".mp3", ".mp4", ".wav", ".m4a", ".mov", ".avi", ".mkv", ".flac"}
ARC = {".zip", ".7z", ".rar", ".tar", ".gz", ".iso"}
OFF = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
CODE = {".py", ".js", ".ts", ".sql", ".db", ".sqlite", ".bin", ".exe", ".dll"}

ACTIONS = {
    "native_text": "status batch → train",
    "office_pdf": "extract/OCR if Medical-Navy gold else defer",
    "image": "OCR queue only gold; else skip/catalog",
    "audio_video": "STT ladder / catalog-only",
    "archive": "catalog-only / nested land later",
    "missing_file": "ghost clear / repoint",
    "code_data": "skip twin train",
    "no_dest": "registry repair",
    "other": "manual spot-check",
}


def main() -> int:
    con = sqlite3.connect(str(DB), timeout=60)
    con.row_factory = sqlite3.Row
    by_status = dict(
        con.execute(
            "SELECT COALESCE(process_status,'null'), COUNT(*) FROM ingest GROUP BY 1"
        ).fetchall()
    )
    rows = con.execute(
        """SELECT dest_path, process_status FROM ingest
           WHERE process_status IS NULL OR process_status='unprocessed'
           LIMIT 8000"""
    ).fetchall()

    ext_c: Counter[str] = Counter()
    bucket_c: Counter[str] = Counter()
    examples = {k: [] for k in ACTIONS}

    scanned = 0
    for r in rows:
        dest = r["dest_path"] or ""
        p = Path(dest) if dest else None
        scanned += 1
        if not dest:
            bucket_c["no_dest"] += 1
            ext_c["(none)"] += 1
            continue
        ext = p.suffix.lower() if p else ""
        ext_c[ext or "(none)"] += 1
        exists = bool(p and p.is_file())
        if not exists:
            bucket = "missing_file"
        elif ext in TEXT_EXT:
            bucket = "native_text"
        elif ext in IMG:
            bucket = "image"
        elif ext in AV:
            bucket = "audio_video"
        elif ext in ARC:
            bucket = "archive"
        elif ext in OFF:
            bucket = "office_pdf"
        elif ext in CODE:
            bucket = "code_data"
        else:
            bucket = "other"
        bucket_c[bucket] += 1
        if len(examples[bucket]) < 3:
            examples[bucket].append(dest[:140])

    extracted = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE process_status='extracted'"
    ).fetchone()[0]
    ctx = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE process_status='context_enriched'"
    ).fetchone()[0]
    deriv = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE process_status='derivative_ok'"
    ).fetchone()[0]
    con.close()

    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "sample_unprocessed": scanned,
        "by_status": by_status,
        "buckets": dict(bucket_c),
        "top_ext": ext_c.most_common(20),
        "examples": examples,
        "pipeline": {"extracted": extracted, "context_enriched": ctx, "derivative_ok": deriv},
    }
    JSON.parent.mkdir(parents=True, exist_ok=True)
    JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Unprocessed triage — {payload['at']}",
        "",
        f"**Sampled unprocessed rows:** {scanned} (cap 8000)",
        "",
        "## process_status totals (full registry)",
        "| Status | Count |",
        "|--------|------:|",
    ]
    for k, v in sorted(by_status.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "## Unprocessed buckets (sample)",
        "| Bucket | Count | Next action |",
        "|--------|------:|-------------|",
    ]
    for k, v in sorted(bucket_c.items(), key=lambda kv: -kv[1]):
        lines.append(f"| **{k}** | {v} | {ACTIONS.get(k, '?')} |")
    lines += ["", "## Top extensions (sample)", "| Ext | Count |", "|-----|------:|"]
    for e, c in ext_c.most_common(15):
        lines.append(f"| `{e}` | {c} |")
    lines += ["", "## Examples", ""]
    for b, exs in examples.items():
        if not exs:
            continue
        lines.append(f"### {b}")
        for e in exs:
            lines.append(f"- `{e}`")
    lines += [
        "",
        f"JSON: `{JSON}`",
        "",
        "Research: post-OCR twin canon — do not OCR-all; bucket first.",
        "[[Operations/logs/next-five-primary-actions-2026-07-18]]",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"scanned": scanned, "buckets": dict(bucket_c), "pipeline": payload["pipeline"]}, indent=2))
    print("WROTE", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
