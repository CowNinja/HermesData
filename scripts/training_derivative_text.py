#!/usr/bin/env python3
"""P1 processor: plain text + digital PDF → .train.md sidecar (idempotent).

No deletes. Fail soft. Class-agnostic (caller enforces touch policy).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from modality_detect import detect


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_sidecar(src: Path, text: str, meta: dict) -> Path:
    out = Path(str(src) + ".train.md")
    meta_path = Path(str(src) + ".train.meta.json")
    header = f"---\nsource: {src}\nprocessed_at: {utc()}\n---\n\n"
    out.write_text(header + (text or ""), encoding="utf-8", errors="replace")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out


def extract_text_file(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), "ok"
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace"), "weak"


def extract_pdf(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except Exception as e:
        return "", f"no_pypdf:{e}"
    try:
        r = PdfReader(str(path))
        parts = []
        for i, page in enumerate(r.pages):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            parts.append(f"## Page {i+1}\n{t}")
        text = "\n\n".join(parts).strip()
        # crude scan detect: very little text
        if len(re.sub(r"\s+", "", text)) < 40:
            return text, "needs_ocr"
        return text, "ok"
    except Exception as e:
        return "", f"fail:{e}"


def process_one(path: Path) -> dict:
    info = detect(path)
    mod = info["modality"]
    if mod in ("text", "code"):
        text, quality = extract_text_file(path)
    elif mod == "pdf":
        text, quality = extract_pdf(path)
    else:
        return {
            "path": str(path),
            "skipped": True,
            "reason": f"modality {mod} not in P1 text/pdf",
            **info,
        }
    meta = {
        "source": str(path),
        "modality": mod,
        "process": info["process"],
        "quality": quality,
        "processed_at": utc(),
        "chars": len(text or ""),
    }
    if quality == "needs_ocr":
        meta["next"] = "ocr_pipeline"
        # still write weak extract if any
    out = write_sidecar(path, text or "[no text extracted]", meta)
    return {"path": str(path), "train_md": str(out), "quality": quality, "chars": len(text or "")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()
    results = []
    for a in args.paths:
        p = Path(a)
        if not p.is_file():
            results.append({"path": a, "error": "not a file"})
            continue
        # idempotent
        if Path(str(p) + ".train.md").exists():
            results.append({"path": a, "skipped": True, "reason": "exists"})
            continue
        results.append(process_one(p))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
