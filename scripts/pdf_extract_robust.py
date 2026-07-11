#!/usr/bin/env python3
"""Robust PDF text extraction for training — fail-soft with quality flags.

Strategies (in order):
1) pypdf extract
2) retry with strict=False / different reader flags
3) mark needs_ocr if little/no text (scan or corrupt)
4) never crash the wave

Writes sidecar: <file>.extract.json + optional .train.md body when enough text.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_pypdf(path: Path) -> tuple[str, list[str]]:
    notes: list[str] = []
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:
                notes.append(f"page_{i}_err:{e}")
        text = "\n".join(parts)
    except Exception as e:
        notes.append(f"pypdf_fail:{e}")
    return text, notes


def quality(text: str, size: int) -> dict:
    t = (text or "").strip()
    alnum = sum(c.isalnum() for c in t)
    ratio = alnum / max(len(t), 1)
    # Jeff policy: when in doubt, re-OCR (old OCR 10+ years may be bad)
    if len(t) < 40 and size > 50_000:
        status = "needs_ocr"
        reason = "little_text_large_file_likely_scan_or_corrupt"
    elif len(t) < 40:
        status = "needs_ocr" if size > 5_000 else "empty_or_stub"
        reason = "almost_no_text_prefer_reocr" if size > 5_000 else "almost_no_text"
    elif ratio < 0.45:
        status = "needs_ocr"
        reason = "questionable_text_quality_reocr"
    elif len(t) < 200 and size > 100_000:
        status = "needs_ocr"
        reason = "sparse_text_large_file_reocr"
    else:
        status = "ok_text"
        reason = "extractable"
    return {
        "status": status,
        "reason": reason,
        "chars": len(t),
        "alnum_ratio": round(ratio, 3),
        "twin_useful": status == "ok_text" and len(t) >= 200,
    }


def process(path: Path, write_train: bool = True) -> dict:
    path = Path(path)
    size = path.stat().st_size if path.is_file() else 0
    text, notes = extract_pypdf(path)
    q = quality(text, size)
    rec = {
        "path": str(path),
        "size": size,
        "checked_at": utc(),
        "extract_notes": notes,
        **q,
    }
    side = Path(str(path) + ".extract.json")
    side.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    if write_train and q["status"] == "ok_text" and len(text.strip()) >= 80:
        train = Path(str(path) + ".train.md")
        body = (
            f"# Extract: {path.name}\n\n"
            f"- source: `{path}`\n"
            f"- quality: {q['status']} ({q['reason']})\n"
            f"- chars: {q['chars']}\n\n"
            f"---\n\n{text.strip()[:50000]}\n"
        )
        train.write_text(body, encoding="utf-8")
        rec["train_md"] = str(train)
    if q["status"] in {"needs_ocr", "low_quality_text"}:
        # marker only — OCR engine later
        flag = Path(str(path) + ".needs_ocr")
        flag.write_text(
            f"needs_ocr\nreason={q['reason']}\nsize={size}\nat={utc()}\n",
            encoding="utf-8",
        )
        rec["needs_ocr_flag"] = str(flag)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--no-train", action="store_true")
    args = ap.parse_args()
    out = []
    for p in args.paths:
        try:
            out.append(process(Path(p), write_train=not args.no_train))
        except Exception as e:
            out.append({"path": p, "status": "error", "error": str(e)})
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
