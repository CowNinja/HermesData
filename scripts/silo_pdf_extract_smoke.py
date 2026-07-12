#!/usr/bin/env python3
"""Capped digital PDF text extract for silo Medical/Navy shelves (pypdf).

ocr-and-documents skill: pymupdf preferred when present; pypdf fallback.
Does not block drain. Writes .ocr.md when text is useful.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
DEFAULT_ROOTS = [
    SILO / "Medical-Records",
    SILO / "Navy-Service",
]
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-pdf-extract-smoke-latest.md")


def extract_pdf(path: Path, max_chars: int = 8000) -> tuple[str, str]:
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(str(path))
        parts = []
        for page in doc:
            parts.append(page.get_text() or "")
            if sum(len(x) for x in parts) >= max_chars:
                break
        doc.close()
        return "\n".join(parts)[:max_chars], "pymupdf"
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        r = PdfReader(str(path))
        parts = []
        for page in r.pages:
            parts.append(page.extract_text() or "")
            if sum(len(x) for x in parts) >= max_chars:
                break
        return "\n".join(parts)[:max_chars], "pypdf"
    except Exception:
        return "", "none"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--min-chars", type=int, default=80)
    args = ap.parse_args()

    written = 0
    scanned = 0
    samples = []
    engine_used = "none"
    for root in DEFAULT_ROOTS:
        if not root.is_dir():
            continue
        for p in root.rglob("*.pdf"):
            if p.name.startswith("00-"):
                continue
            ocr_path = Path(str(p) + ".ocr.md")
            if ocr_path.is_file() and ocr_path.stat().st_size > 50:
                continue
            scanned += 1
            text, eng = extract_pdf(p)
            engine_used = eng
            if len(text.strip()) < args.min_chars:
                continue
            body = (
                f"# Extract {p.name}\n\n"
                f"- engine: {eng}\n"
                f"- at: {datetime.now(timezone.utc).isoformat()}\n"
                f"- chars: {len(text)}\n\n"
                f"```\n{text[:6000]}\n```\n"
            )
            ocr_path.write_text(body, encoding="utf-8")
            written += 1
            samples.append(f"{p.name[:55]} chars={len(text)} eng={eng}")
            if written >= args.limit:
                break
        if written >= args.limit:
            break

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"# PDF extract smoke {datetime.now(timezone.utc).isoformat()}\n\n"
        f"scanned={scanned} written={written} engine={engine_used}\n\n"
        + "\n".join(f"- {s}" for s in samples),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "engine": engine_used,
                "scanned": scanned,
                "written": written,
                "samples": samples[:6],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
