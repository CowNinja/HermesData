#!/usr/bin/env python3
"""Unified robust extract/OCR ladder for max twin training text.

Ladder (fail-soft, never crash wave):
  1) Digital PDF text (pypdf strict=False)
  2) Quality gate — short/garbled/sparse → needs_ocr
  3) Images (png/jpg/tif/webp/bmp) → Tesseract + PIL preprocess
  4) PDF scans → pdftoppm (tool_paths) → Tesseract pages
  5) Optional pypdfium2/PIL render fallback if no pdftoppm
  6) Write best text to .ocr.md + .extract.json + .train.md when useful
  7) Leave .needs_ocr if still inadequate (retry later)

Jeff: re-OCR questionable/old OCR; max training signal per file.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
TOOL_PATHS = Path(r"D:\HermesData\config\tool_paths.json")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-robust-ocr-latest.md")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXT = {".pdf"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def tools() -> dict:
    try:
        return json.loads(TOOL_PATHS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tesseract_bin() -> str | None:
    tp = tools().get("tesseract")
    if tp and Path(tp).is_file():
        return tp
    return shutil.which("tesseract")


def pdftoppm_bin() -> str | None:
    tp = tools().get("pdftoppm")
    if tp and Path(tp).is_file():
        return tp
    return shutil.which("pdftoppm")


def quality(text: str, size: int) -> dict[str, Any]:
    t = (text or "").strip()
    alnum = sum(c.isalnum() for c in t)
    ratio = alnum / max(len(t), 1)
    # garbage patterns: replacement chars, mostly symbols
    bad = t.count("\ufffd") + t.count("�")
    if len(t) < 40 and size > 50_000:
        status, reason = "needs_ocr", "little_text_large_file"
    elif len(t) < 40:
        status, reason = ("needs_ocr", "almost_no_text") if size > 3_000 else ("empty", "tiny_or_stub")
    elif len(t) >= 800 and bad < 50:
        # plenty of extractable text even if OCR noisy
        status, reason = "ok_text", "long_extract"
    elif ratio < 0.40 or bad > 20:
        status, reason = "needs_ocr", "garbled_or_low_alnum"
    elif len(t) < 180 and size > 80_000:
        status, reason = "needs_ocr", "sparse_text_large_file"
    else:
        status, reason = "ok_text", "extractable"
    return {
        "status": status,
        "reason": reason,
        "chars": len(t),
        "alnum_ratio": round(ratio, 3),
        "twin_useful": status == "ok_text" and len(t) >= 120,
    }


def extract_pypdf(path: Path) -> tuple[str, list[str]]:
    notes: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:
                notes.append(f"page_{i}:{e}")
        return "\n".join(parts), notes
    except Exception as e:
        notes.append(f"pypdf:{e}")
        return "", notes


def preprocess_image(img: Path) -> Path:
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance

        im = Image.open(img)
        im = ImageOps.grayscale(im)
        # upscale small pages for Tesseract
        w, h = im.size
        if max(w, h) < 2000:
            im = im.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
        im = ImageOps.autocontrast(im)
        im = ImageEnhance.Contrast(im).enhance(1.4)
        try:
            im = im.filter(ImageFilter.MedianFilter(size=3))
        except Exception:
            pass
        # skip hard binarize — destroys grey medical scan text
        tmp = img.with_name(img.stem + ".__prep.png")
        im.save(tmp)
        return tmp
    except Exception:
        return img


def ocr_image(img: Path, tess: str) -> str:
    prep = preprocess_image(img)
    try:
        best = ""
        for psm in ("6", "4", "3", "11"):
            r = subprocess.run(
                [tess, str(prep), "stdout", "-l", "eng", "--oem", "1", "--psm", psm],
                capture_output=True,
                text=True,
                timeout=180,
            )
            text = r.stdout or ""
            if len(text.strip()) > len(best.strip()):
                best = text
            if len(best.strip()) >= 200:
                break
        return best
    finally:
        if prep != img and prep.is_file():
            try:
                prep.unlink()
            except Exception:
                pass


def pdf_to_pngs(pdf: Path, out_dir: Path, max_pages: int = 8) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ppm = pdftoppm_bin()
    if ppm:
        prefix = out_dir / "page"
        subprocess.run(
            [ppm, "-png", "-r", "300", "-l", str(max_pages), str(pdf), str(prefix)],
            capture_output=True,
            timeout=240,
        )
        pages = sorted(out_dir.glob("page*.png"))
        if pages:
            return pages
    # fallback: pypdfium2
    try:
        import pypdfium2 as pdfium  # type: ignore

        doc = pdfium.PdfDocument(str(pdf))
        out = []
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            bitmap = page.render(scale=2)
            pil = bitmap.to_pil()
            dest = out_dir / f"page-{i+1:02d}.png"
            pil.save(dest)
            out.append(dest)
        return out
    except Exception:
        pass
    # last resort: pymupdf render
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(str(pdf))
        out = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3))
            dest = out_dir / f"page-{i+1:02d}.png"
            pix.save(str(dest))
            out.append(dest)
        doc.close()
        return out
    except Exception:
        return []


def ocr_pdf(pdf: Path, tess: str, max_pages: int = 8, short_temp_copy: bool = True) -> tuple[str, list[str]]:
    # Poppler fails on some long Windows paths / parentheses — copy to short temp
    _tmp_dir = None
    if short_temp_copy:
        import tempfile, shutil
        s = str(pdf)
        if len(s) > 180 or "(" in s or ")" in s:
            _tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_"))
            short = _tmp_dir / "in.pdf"
            shutil.copy2(pdf, short)
            pdf = short
    notes: list[str] = []
    work = Path(tempfile.mkdtemp(prefix="silo_ocr_"))
    try:
        pages = pdf_to_pngs(pdf, work, max_pages=max_pages)
        if not pages:
            notes.append("no_page_render")
            return "", notes
        texts = []
        for pg in pages:
            texts.append(ocr_image(pg, tess))
        return "\n\n".join(texts), notes
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_sidecars(path: Path, text: str, rec: dict, write_train: bool) -> None:
    ocr_md = Path(str(path) + ".ocr.md")
    extract_json = Path(str(path) + ".extract.json")
    body = (
        f"# OCR/Extract — {path.name}\n\n"
        f"- at: {rec.get('at')}\n"
        f"- status: {rec.get('quality', {}).get('status')}\n"
        f"- engine: {rec.get('engine')}\n"
        f"- chars: {rec.get('quality', {}).get('chars')}\n"
        f"- reason: {rec.get('quality', {}).get('reason')}\n\n"
        f"```\n{(text or '')[:12000]}\n```\n"
    )
    ocr_md.write_text(body, encoding="utf-8")
    extract_json.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    if write_train and rec.get("quality", {}).get("twin_useful"):
        train = Path(str(path) + ".train.md")
        # don't clobber large existing train
        if not train.is_file() or train.stat().st_size < 100:
            train.write_text(
                f"# Train extract — {path.name}\n\n"
                f"source: robust_ocr_ladder\n\n"
                f"{(text or '')[:8000]}\n",
                encoding="utf-8",
            )
    flag = Path(str(path) + ".needs_ocr")
    if rec.get("quality", {}).get("status") == "needs_ocr":
        flag.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    elif flag.is_file():
        try:
            flag.unlink()
        except Exception:
            pass


def process_one(path: Path, tess: str | None, write_train: bool, max_pages: int) -> dict:
    path = Path(path)
    size = path.stat().st_size if path.is_file() else 0
    ext = path.suffix.lower()
    notes: list[str] = []
    text = ""
    engine = "none"

    if ext in PDF_EXT:
        text, n1 = extract_pypdf(path)
        notes.extend(n1)
        engine = "pypdf"
        q = quality(text, size)
        if q["status"] == "needs_ocr" and tess:
            otext, n2 = ocr_pdf(path, tess, max_pages=max_pages)
            notes.extend(n2)
            if len(otext.strip()) > len(text.strip()):
                text = otext
                engine = "tesseract+pdftoppm"
                q = quality(text, size)
        rec = {
            "path": str(path),
            "size": size,
            "engine": engine,
            "quality": q,
            "notes": notes,
            "at": utc(),
        }
        write_sidecars(path, text, rec, write_train)
        return rec

    if ext in IMAGE_EXT:
        if not tess:
            rec = {
                "path": str(path),
                "size": size,
                "engine": "none",
                "quality": {"status": "needs_ocr", "reason": "no_tesseract", "chars": 0},
                "notes": ["tesseract_missing"],
                "at": utc(),
            }
            write_sidecars(path, "", rec, write_train)
            return rec
        text = ocr_image(path, tess)
        engine = "tesseract_image"
        q = quality(text, size)
        rec = {
            "path": str(path),
            "size": size,
            "engine": engine,
            "quality": q,
            "notes": notes,
            "at": utc(),
        }
        write_sidecars(path, text, rec, write_train)
        return rec

    return {"path": str(path), "status": "skip_ext", "ext": ext}


def iter_candidates(roots: list[Path], limit: int) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name.startswith("00-") or p.name.startswith("."):
                continue
            if p.suffix.lower() not in PDF_EXT | IMAGE_EXT:
                continue
            # skip if already twin-useful extract
            ej = Path(str(p) + ".extract.json")
            if ej.is_file():
                try:
                    d = json.loads(ej.read_text(encoding="utf-8"))
                    if d.get("quality", {}).get("twin_useful"):
                        continue
                except Exception:
                    pass
            out.append(p)
            if len(out) >= limit * 3:
                break
        if len(out) >= limit * 3:
            break
    return out[: limit * 3]


def main() -> int:
    # force-reocr handled via args after parse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max-pages", type=int, default=6)
    ap.add_argument("--no-train", action="store_true")
    ap.add_argument(
        "--roots",
        nargs="*",
        default=[
            str(SILO / "Medical-Records"),
            str(SILO / "Navy-Service"),
        ],
    )
    ap.add_argument("paths", nargs="*", help="Optional explicit files")
    args = ap.parse_args()

    tess = tesseract_bin()
    results = []
    paths = [Path(p) for p in args.paths] if args.paths else []
    if not paths:
        paths = iter_candidates([Path(r) for r in args.roots], args.limit)

    done = 0
    for p in paths:
        if done >= args.limit:
            break
        try:
            rec = process_one(p, tess, write_train=not args.no_train, max_pages=args.max_pages)
            results.append(rec)
            done += 1
        except Exception as e:
            results.append({"path": str(p), "error": str(e)[:200]})

    ok = sum(1 for r in results if (r.get("quality") or {}).get("status") == "ok_text")
    need = sum(1 for r in results if (r.get("quality") or {}).get("status") == "needs_ocr")
    twin = sum(1 for r in results if (r.get("quality") or {}).get("twin_useful"))

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Robust OCR ladder — {utc()}",
        "",
        f"- tesseract: `{tess}`",
        f"- pdftoppm: `{pdftoppm_bin()}`",
        f"- processed: **{len(results)}** · ok_text **{ok}** · needs_ocr **{need}** · twin_useful **{twin}**",
        "",
        "| Engine | Status | Chars | File |",
        "|--------|--------|------:|------|",
    ]
    for r in results[:40]:
        q = r.get("quality") or {}
        lines.append(
            f"| {r.get('engine', r.get('status', '?'))} | {q.get('status', r.get('error', '?'))} | "
            f"{q.get('chars', 0)} | `{Path(r.get('path', '')).name[:50]}` |"
        )
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "processed": len(results),
                "ok_text": ok,
                "needs_ocr": need,
                "twin_useful": twin,
                "tesseract": bool(tess),
                "pdftoppm": bool(pdftoppm_bin()),
                "receipt": str(LOG),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
