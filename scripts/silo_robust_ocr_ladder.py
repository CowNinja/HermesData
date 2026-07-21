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
    bad = t.count("\ufffd") + t.count("\uFFFD")
    n = len(t)
    # digital/short stubs
    if n < 40 and size > 50_000:
        status, reason = "needs_ocr", "little_text_large_file"
    elif n < 40:
        status, reason = ("needs_ocr", "almost_no_text") if size > 3_000 else ("empty", "tiny_or_stub")
    elif n >= 80 and bad < 50 and ratio >= 0.30:
        # OCR diagrams / short clinical notes still train-useful
        status, reason = "ok_text", "extractable"
    elif ratio < 0.30 or bad > 40:
        status, reason = "needs_ocr", "garbled_or_low_alnum"
    elif n < 180 and size > 400_000:
        status, reason = "needs_ocr", "sparse_text_large_file"
    else:
        status, reason = "ok_text", "extractable"
    twin = n >= 40 and ratio >= 0.28 and bad < 80
    if status == "ok_text":
        twin = n >= 40
    return {
        "status": status,
        "reason": reason,
        "chars": n,
        "alnum_ratio": round(ratio, 3),
        "twin_useful": twin,
    }



def pdftotext_bin() -> str | None:
    tp = tools().get("pdftotext")
    if tp and Path(tp).is_file():
        return tp
    # sibling of pdftoppm
    ppm = pdftoppm_bin()
    if ppm:
        sib = Path(ppm).with_name("pdftotext.exe")
        if sib.is_file():
            return str(sib)
        sib2 = Path(ppm).with_name("pdftotext")
        if sib2.is_file():
            return str(sib2)
    return shutil.which("pdftotext")


def extract_digital_pdf(path: Path) -> tuple[str, list[str]]:
    """Digital text layer: pypdf if present, else poppler pdftotext (no Python dep)."""
    notes: list[str] = []
    # 1) pypdf optional
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path), strict=False)
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:
                notes.append(f"page_{i}:{e}")
        text = "\n".join(parts)
        if text.strip():
            notes.append("engine:pypdf")
            return text, notes
        notes.append("pypdf_empty")
    except Exception as e:
        notes.append(f"pypdf:{type(e).__name__}")

    # 2) poppler pdftotext (reliable Windows path; no pip)
    bin_ = pdftotext_bin()
    if bin_:
        try:
            r = subprocess.run(
                [bin_, "-layout", "-enc", "UTF-8", str(path), "-"],
                capture_output=True,
                timeout=120,
            )
            # pdftotext writes UTF-8 to stdout when dest is -
            text = (r.stdout or b"").decode("utf-8", errors="replace")
            if text.strip():
                notes.append("engine:pdftotext")
                return text, notes
            notes.append("pdftotext_empty")
        except Exception as e:
            notes.append(f"pdftotext:{type(e).__name__}:{e}")
    else:
        notes.append("pdftotext_missing")
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


def pdf_to_pngs(pdf: Path, out_dir: Path, max_pages: int = 8) -> tuple[list[Path], list[str]]:
    """Render PDF pages to PNG. Returns (pages, notes). Notes carry password/errors."""
    out_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    ppm = pdftoppm_bin()
    if ppm:
        prefix = out_dir / "page"
        try:
            cp = subprocess.run(
                [ppm, "-png", "-r", "300", "-l", str(max_pages), str(pdf), str(prefix)],
                capture_output=True,
                timeout=240,
                text=True,
                errors="replace",
            )
            err = ((cp.stderr or "") + "\n" + (cp.stdout or "")).strip()
            if err:
                notes.append("pdftoppm:" + err[:300].replace("\n", " | "))
            if cp.returncode != 0 and not err:
                notes.append(f"pdftoppm_rc={cp.returncode}")
        except Exception as e:
            notes.append(f"pdftoppm_exc:{type(e).__name__}:{e}"[:200])
        pages = sorted(out_dir.glob("page*.png"))
        if pages:
            return pages, notes
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
        if out:
            notes.append("engine:pypdfium2")
        return out, notes
    except Exception as e:
        notes.append(f"pypdfium2_exc:{type(e).__name__}:{e}"[:160])
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
        if out:
            notes.append("engine:pymupdf")
        return out, notes
    except Exception as e:
        notes.append(f"pymupdf_exc:{type(e).__name__}:{e}"[:160])
        return [], notes


def ocr_pdf(pdf: Path, tess: str, max_pages: int = 8, short_temp_copy: bool = True) -> tuple[str, list[str]]:
    # Poppler fails on some long Windows paths / parentheses — copy to short temp
    _tmp_dir = None
    if short_temp_copy:
        s = str(pdf)
        if len(s) > 180 or "(" in s or ")" in s:
            _tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_"))
            short = _tmp_dir / "in.pdf"
            shutil.copy2(pdf, short)
            pdf = short
    notes: list[str] = []
    work = Path(tempfile.mkdtemp(prefix="silo_ocr_"))
    try:
        pages, n2 = pdf_to_pngs(pdf, work, max_pages=max_pages)
        notes.extend(n2)
        if not pages:
            notes.append("no_page_render")
            return "", notes
        texts = []
        for pg in pages:
            texts.append(ocr_image(pg, tess))
        return "\n\n".join(texts), notes
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if _tmp_dir is not None:
            shutil.rmtree(_tmp_dir, ignore_errors=True)


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
        tbody = (
            f"# Train extract — {path.name}\n\n"
            f"source: robust_ocr_ladder\n"
            f"engine: {rec.get('engine')}\n"
            f"status: {rec.get('quality', {}).get('status')}\n\n"
            f"{(text or '')[:12000]}\n"
        )
        if (not train.is_file()) or train.stat().st_size < max(80, int(len(tbody) * 0.5)):
            train.write_text(tbody, encoding="utf-8")
    flag = Path(str(path) + ".needs_ocr")
    st = rec.get("quality", {}).get("status")
    if st in ("needs_ocr", "encrypted"):
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
        text, n1 = extract_digital_pdf(path)
        notes.extend(n1)
        engine = "digital_pdf"
        for n in n1:
            if n.startswith("engine:"):
                engine = n.split(":", 1)[1]
        q = quality(text, size)
        if q["status"] == "needs_ocr" and tess:
            otext, n2 = ocr_pdf(path, tess, max_pages=max_pages)
            notes.extend(n2)
            if len(otext.strip()) > len(text.strip()):
                text = otext
                engine = "tesseract+pdftoppm"
                q = quality(text, size)
            # encrypted / password PDFs: fail closed, do not loop forever as needs_ocr
            joined = " ".join(str(x) for x in notes).lower()
            if (not text.strip()) and any(
                x in joined for x in ("incorrect password", "password", "encrypted")
            ):
                q = {
                    "status": "encrypted",
                    "reason": "password_protected",
                    "chars": 0,
                    "alnum_ratio": 0.0,
                    "twin_useful": False,
                }
                engine = "encrypted_pdf"
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


def _ocr_score(path: Path) -> int:
    """Higher = cook first. Prefer flagged PDFs + clinical names; skip portraits."""
    s = str(path).lower().replace("\\", "/")
    name = path.name.lower()
    ext = path.suffix.lower()
    # hard skips: portraits / chrome
    if re.search(r"(logo|icon|wallpaper|screenshot|portrait|headshot|badge)", name):
        return -1
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        # only keep images that look like scanned docs
        if not re.search(r"(lab|scan|record|note|order|dd214|les|eval|phr|page)", name):
            return -1
    score = 0
    if Path(str(path) + ".needs_ocr").is_file():
        score += 500
    if ext == ".pdf":
        score += 200
    for k, w in (
        ("medical-records", 80),
        ("navy-service", 70),
        ("nmcp", 60),
        ("vamc", 60),
        ("pha", 50),
        ("labwork", 90),
        ("lab", 40),
        ("cnp", 70),
        ("quest", 50),
        ("dd214", 80),
        ("orders", 50),
        ("eval", 40),
        ("les", 40),
        ("bluebutton", 60),
        ("tricare", 40),
        ("chiro", 40),
    ):
        if k in s or k in name:
            score += w
    # deprioritize empty secure-messaging stubs / tiny images later via size
    try:
        sz = path.stat().st_size
        if ext == ".pdf" and sz < 1500:
            score -= 100
        if sz > 50_000:
            score += 20
        if sz > 200_000:
            score += 20
    except Exception:
        pass
    # already attempted extract with low chars — still allow if needs_ocr flag
    ej = Path(str(path) + ".extract.json")
    if ej.is_file():
        try:
            d = json.loads(ej.read_text(encoding="utf-8"))
            q = d.get("quality") or {}
            if q.get("twin_useful"):
                return -1
            if q.get("status") == "encrypted":
                return -1
            if q.get("status") == "empty" and not Path(str(path) + ".needs_ocr").is_file():
                score -= 50
        except Exception:
            pass
    return score


def iter_candidates(roots: list[Path], limit: int) -> list[Path]:
    scored: list[tuple[int, Path]] = []
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
            sc = _ocr_score(p)
            if sc < 0:
                continue
            scored.append((sc, p))
            if len(scored) >= max(limit * 40, 200):
                break
        if len(scored) >= max(limit * 40, 200):
            break
    scored.sort(key=lambda x: (-x[0], str(x[1]).lower()))
    return [p for _, p in scored[: max(limit * 3, limit)]]


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
