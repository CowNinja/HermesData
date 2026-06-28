"""
Content Extraction Helper - Advanced version (updated 2026-06-26)
Supports:
- Digital text (pypdf)
- Advanced OCR for scans/PDFs/images via tesseract (subprocess for robustness)
- Basic corruption detection
- Audio transcription stub (whisper)
- Entity/keyword extraction for digital footprint
"""

import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import os

# Config
TESSERACT_CMD = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
WHISPER_MODEL = "base"  # small model for speed; use "small" or "medium" for better accuracy

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except:
    HAS_PYPDF = False

def extract_text(path: Path, max_chars: int = 4000) -> str:
    """Digital text extraction."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf" and HAS_PYPDF:
        try:
            reader = PdfReader(str(p))
            text = ""
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
                if len(text) > max_chars:
                    break
            return text[:max_chars]
        except:
            pass
    if suffix in (".txt", ".md", ".csv"):
        try:
            return p.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        except:
            pass
    return ""

def _run_tesseract(image_path: str, lang: str = "eng") -> str:
    """Robust tesseract call via subprocess (bypasses broken venv imports)."""
    if not os.path.exists(TESSERACT_CMD):
        return "[Tesseract not found at " + TESSERACT_CMD + "]"
    try:
        result = subprocess.run(
            [TESSERACT_CMD, image_path, "stdout", "-l", lang],
            capture_output=True, text=True, timeout=60
        )
        return result.stdout.strip()
    except Exception as e:
        return f"[OCR error: {str(e)[:100]}]"

def extract_text_with_ocr(path: Path, max_chars: int = 4000, use_ocr: bool = True) -> str:
    """Digital + OCR for scanned images/PDFs."""
    p = Path(path)
    text = extract_text(p, max_chars)
    if text and len(text.strip()) > 30:
        return text  # good digital text

    if not use_ocr:
        return text or ""

    suffix = p.suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        return _run_tesseract(str(p))[:max_chars]

    if suffix == ".pdf":
        # Try to OCR first page via temp image (requires pdf2image or fallback)
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(p), first_page=1, last_page=1, dpi=150)
            if images:
                tmp = Path("temp_ocr_page.png")
                images[0].save(tmp)
                ocr = _run_tesseract(str(tmp))
                tmp.unlink(missing_ok=True)
                return (text + "\n" + ocr).strip()[:max_chars] if ocr else text
        except Exception as e:
            return text or f"[PDF OCR fallback failed: {str(e)[:80]}]"

    return text or ""

def detect_corruption(path: Path) -> Dict[str, Any]:
    """Basic file integrity and usability checks."""
    p = Path(path)
    result = {"corrupt": False, "issues": [], "repairable": False}
    if not p.exists():
        result["corrupt"] = True
        result["issues"].append("file missing")
        return result
    size = p.stat().st_size
    if size < 100:
        result["issues"].append("very small file")
    try:
        if p.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(str(p))
            if len(r.pages) == 0:
                result["issues"].append("no pages")
    except Exception as e:
        result["corrupt"] = True
        result["issues"].append(f"PDF parse failed: {str(e)[:60]}")
        result["repairable"] = True  # could try qpdf or similar later
    return result

def extract_audio_transcript(path: Path, max_chars: int = 4000) -> str:
    """Audio transcription (whisper). Requires ffmpeg + model download on first use."""
    # Stub: implement full with import whisper; model = whisper.load_model(WHISPER_MODEL)
    # transcript = model.transcribe(str(path))["text"]
    return "[Audio transcription stub - install ffmpeg + run whisper model for full use]"

def enhance_with_content(file_path: str) -> Dict[str, Any]:
    """Full content evaluation for manifest enrichment."""
    p = Path(file_path)
    result = {
        "extracted_text": "",
        "ocr_used": False,
        "corruption": detect_corruption(p),
        "keywords": [],
        "digital_footprint_signals": [],
        "content_length": 0,
    }
    text = extract_text_with_ocr(p)
    result["extracted_text"] = text[:max(2000, len(text))]
    result["content_length"] = len(text)
    result["ocr_used"] = "Tesseract" in text or len(text) > 50 and not any(x in text for x in ["[", "error"])

    lower = text.lower() + " " + p.name.lower()
    for kw in ["va", "dd214", "disability", "medical", "navy", "bloom", "jeff", "1099", "scan", "veteran"]:
        if kw in lower:
            result["keywords"].append(kw)
            result["digital_footprint_signals"].append(kw.upper())

    if "va" in lower or "dd" in lower or "disability" in lower:
        result["digital_footprint_signals"].append("Navy_Medical_History")
    if "1099" in lower or "tax" in lower:
        result["digital_footprint_signals"].append("Financial_Records")

    if result["corruption"]["corrupt"]:
        result["digital_footprint_signals"].append("CORRUPTED_FILE")

    return result
