#!/usr/bin/env python3
"""OCR ladder P1: process *.needs_ocr flags with Tesseract when available.

Preprocess (grayscale/contrast) via PIL when possible.
Writes .ocr.md + updates extract.json; clears needs_ocr on success.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_paths() -> dict:
    try:
        return json.loads(Path(r"D:/HermesData/config/tool_paths.json").read_text(encoding="utf-8"))
    except Exception:
        return {}

def have_tesseract() -> str | None:
    tp = _tool_paths().get("tesseract")
    if tp and Path(tp).is_file():
        return tp
    return shutil.which("tesseract")

def have_pdftoppm() -> str | None:
    tp = _tool_paths().get("pdftoppm")
    if tp and Path(tp).is_file():
        return tp
    return shutil.which("pdftoppm")


def pdf_to_pngs(pdf: Path, out_dir: Path, max_pages: int = 5) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Prefer pdftoppm if present; else try pypdfium2/PIL later
    pdftoppm = have_pdftoppm()
    if pdftoppm:
        prefix = out_dir / "page"
        subprocess.run(
            [pdftoppm, "-png", "-r", "200", "-l", str(max_pages), str(pdf), str(prefix)],
            capture_output=True,
            timeout=120,
        )
        return sorted(out_dir.glob("page*.png"))
    # fallback: only first page via pypdf + report limited
    return []


def ocr_image(img: Path, tess: str) -> str:
    try:
        from PIL import Image, ImageOps, ImageFilter

        im = Image.open(img)
        im = ImageOps.grayscale(im)
        im = ImageOps.autocontrast(im)
        tmp = img.with_suffix(".prep.png")
        im.save(tmp)
        r = subprocess.run(
            [tess, str(tmp), "stdout", "-l", "eng", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        try:
            tmp.unlink()
        except Exception:
            pass
        return r.stdout or ""
    except Exception as e:
        r = subprocess.run(
            [tess, str(img), "stdout", "-l", "eng"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return (r.stdout or "") + f"\n# ocr_note: {e}"


def process_flag(flag: Path, tess: str) -> dict:
    # flag next to original: foo.pdf.needs_ocr
    name = flag.name
    if not name.endswith(".needs_ocr"):
        return {"flag": str(flag), "status": "skip"}
    original = flag.with_name(name[: -len(".needs_ocr")])
    if not original.exists():
        return {"flag": str(flag), "status": "missing_original"}
    texts = []
    notes = []
    if original.suffix.lower() == ".pdf":
        work = flag.parent / f".ocr_work_{original.stem}"
        pages = pdf_to_pngs(original, work)
        if not pages:
            notes.append("no_pdftoppm_or_pages")
            # try pytesseract on nothing — mark pending_poppler
            rec = {
                "status": "blocked_need_pdftoppm",
                "path": str(original),
                "notes": notes,
                "at": utc(),
            }
            Path(str(original) + ".ocr.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
            return rec
        for pg in pages:
            texts.append(ocr_image(pg, tess))
        shutil.rmtree(work, ignore_errors=True)
    elif original.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}:
        texts.append(ocr_image(original, tess))
    else:
        return {"flag": str(flag), "status": "unsupported_type"}

    body = "\n\n".join(t.strip() for t in texts if t.strip())
    ocr_md = Path(str(original) + ".ocr.md")
    ocr_md.write_text(
        f"# OCR: {original.name}\n\n- engine: tesseract\n- at: {utc()}\n\n---\n\n{body[:80000]}\n",
        encoding="utf-8",
    )
    # also train.md if substantial
    if len(body) >= 80:
        Path(str(original) + ".train.md").write_text(
            f"# OCR train extract: {original.name}\n\n{body[:50000]}\n",
            encoding="utf-8",
        )
    try:
        flag.unlink()
    except Exception:
        pass
    rec = {
        "status": "ocr_ok" if len(body) >= 40 else "ocr_weak",
        "chars": len(body),
        "path": str(original),
        "ocr_md": str(ocr_md),
        "at": utc(),
    }
    Path(str(original) + ".ocr.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default=r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Medical-Records",
    )
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    tess = have_tesseract()
    if not tess:
        print(json.dumps({"error": "tesseract_not_on_PATH", "hint": "install tesseract OCR"}))
        return 2
    root = Path(args.root)
    flags = list(root.rglob("*.needs_ocr"))[: args.limit]
    # also generate needs_ocr via robust extract if none
    if not flags:
        print(json.dumps({"flags": 0, "msg": "no needs_ocr flags; run pdf_extract_robust first"}))
        return 0
    out = [process_flag(f, tess) for f in flags]
    print(json.dumps({"tesseract": tess, "processed": len(out), "results": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
