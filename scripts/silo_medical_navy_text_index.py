#!/usr/bin/env python3
"""Lightweight Medical/Navy text harvest from OCR sidecars for Phronesis usefulness.

Scans recent .ocr.md / .train.md under K silo for high-signal tokens and
appends to a master JSONL index (no LLM). Effectiveness > volume.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

K = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
OUT = Path(r"D:\HermesData\state\medical_navy_text_index.jsonl")
STATE = Path(r"D:\HermesData\state\medical_navy_index_state.json")

PATTERNS = [
    (r"\bNMCP\b", "nmcp"),
    (r"\bMRI\b|\bCT scan\b|\bX-?ray\b|\bNIfTI\b|\.dcm\b", "imaging"),
    (r"\bTBI\b|\btraumatic brain\b", "tbi"),
    (r"\bcortisol\b", "cortisol"),
    (r"\bUSS\s+Enterprise\b|\bCVN-?65\b", "enterprise"),
    (r"\bUSS\s+Elrod\b|\bFFG-?55\b", "elrod"),
    (r"\bNCDOC\b|\bSTA-?21\b|\bBOOST\b", "navy_school_cmd"),
    (r"\bO.?Shanick\b|\bBIAV\b|\bBoone\s+BHC\b", "medical_provider"),
    (r"\borders?\b|\beval(uation)?\b|\bLES\b", "personnel_doc"),
    (r"\bDOB\b|\bSSN\b|\bpatient\b", "phi_marker"),
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    seen = set()
    if STATE.is_file():
        try:
            seen = set(json.loads(STATE.read_text(encoding="utf-8")).get("seen") or [])
        except Exception:
            seen = set()

    hits = 0
    scanned = 0
    # Prefer Jeff-first domain roots (avoid full-K rglob hang).
    # Medical-Records / Navy-Service are canonical shelves; Medical is legacy alias.
    roots = [
        K / "Medical-Records",
        K / "Navy-Service",
        K / "Medical",
        K / "Core-Personal" / "Career",
    ]
    files: list[Path] = []
    max_files = 3000
    for root in roots:
        if not root.exists():
            continue
        for pat in ("**/*.ocr.md", "**/*.train.md"):
            try:
                for p in root.glob(pat):
                    files.append(p)
                    if len(files) >= max_files:
                        break
            except Exception:
                pass
            if len(files) >= max_files:
                break
        if len(files) >= max_files:
            break

    # newest first
    files = sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as out:
        for p in files:
            if hits >= args.limit:
                break
            key = str(p)
            if key in seen:
                continue
            scanned += 1
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")[:50000]
            except Exception:
                seen.add(key)
                continue
            tags = []
            for rx, tag in PATTERNS:
                if re.search(rx, text, re.I):
                    tags.append(tag)
            seen.add(key)
            if not tags:
                continue
            rec = {
                "at": utc(),
                "path": key,
                "tags": tags,
                "chars": len(text),
                "snippet": re.sub(r"\s+", " ", text[:240]).strip(),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            hits += 1

    STATE.write_text(
        json.dumps({"at": utc(), "seen": list(seen)[-5000:], "last_hits": hits}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"scanned": scanned, "indexed": hits, "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
