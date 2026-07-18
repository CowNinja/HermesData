#!/usr/bin/env python3
"""Detect processing modality for a file path (rules-first)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# router key → process_status hint
EXT = {
    ".txt": "text",
    ".md": "text",
    ".csv": "text",
    ".json": "text",
    ".yaml": "text",
    ".yml": "text",
    ".log": "text",
    ".html": "text",  # takeout Keep/Voice — Jeff 2026-07-18 land wave
    ".htm": "text",
    ".rtf": "text",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".webp": "image",
    ".gif": "image",
    ".bmp": "image",
    ".docx": "office",
    ".xlsx": "office",
    ".pptx": "office",
    ".doc": "office_legacy",
    ".xls": "office_legacy",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".flac": "audio",
    ".ogg": "audio",
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".avi": "video",
    ".eml": "email",
    ".mbox": "email",
    ".pst": "email_archive",
    ".zip": "archive",
    ".7z": "archive",
    ".rar": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".gdoc": "google_stub",
    ".gsheet": "google_stub",
    ".gslides": "google_stub",
    ".gmap": "google_stub",
    ".gscript": "google_stub",
    ".exe": "binary_skip",
    ".dll": "binary_skip",
    ".sys": "binary_skip",
}


def detect(path: str | Path) -> dict:
    p = Path(path)
    ext = p.suffix.lower()
    mod = EXT.get(ext, "unknown")
    process = {
        "text": "extract_text",
        "code": "extract_text",
        "pdf": "pdf_smart",  # digital vs scan decided later
        "image": "ocr_or_caption",
        "office": "office_extract",
        "office_legacy": "office_legacy",
        "audio": "asr",
        "video": "asr_from_video",
        "email": "email_parse",
        "email_archive": "email_archive",
        "archive": "unpack",
        "google_stub": "needs_export",
        "binary_skip": "skip",
        "unknown": "quarantine",
    }.get(mod, "quarantine")
    return {
        "path": str(p),
        "ext": ext,
        "modality": mod,
        "process": process,
        "train_sidecar": f"{p.name}.train.md",
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: modality_detect.py <path>...")
        return 2
    for a in sys.argv[1:]:
        print(json.dumps(detect(a), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
