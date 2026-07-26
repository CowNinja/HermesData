#!/usr/bin/env python3
"""Capped digital PDF text extract for silo Medical/Navy shelves (pypdf).

ocr-and-documents skill: pymupdf preferred when present; pypdf fallback.
Does not block drain. Writes .ocr.md when text is useful.

Thin/empty text-layer PDFs (scanned/image-only) get a .needs_ocr.json marker
and a handoff list so pypdf waves do not thrash them forever. OCR ladder owns
those paths (pypdf docs: digitally-born vs scanned; OCRmyPDF cookbook).
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
HANDOFF = Path(r"D:\HermesData\state\pdf_needs_ocr_handoff.txt")


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
    ap.add_argument("--path", help="Single PDF file OR directory root")
    ap.add_argument(
        "--roots",
        nargs="*",
        default=[str(r) for r in DEFAULT_ROOTS],
        help="Discovery roots when --path is not a file",
    )
    args = ap.parse_args()

    written = 0
    scanned = 0
    samples: list[str] = []
    engine_used = "none"
    targets: list[Path] = []
    needs_ocr_paths: list[str] = []
    path_obj = Path(args.path) if args.path else None

    if path_obj is not None and path_obj.is_file():
        targets = [path_obj]
    else:
        roots = list(args.roots)
        # Dir --path is exclusive scope (no silent bleed into default roots).
        if path_obj is not None and path_obj.is_dir():
            roots = [str(path_obj)]
        for root in roots:
            r = Path(root)
            if not r.is_dir():
                continue
            for p in r.rglob("*.pdf"):
                if p.name.startswith("00-"):
                    continue
                ocr_path = Path(str(p) + ".ocr.md")
                train_path = Path(str(p) + ".train.md")
                needs_marker = Path(str(p) + ".needs_ocr.json")
                if (ocr_path.is_file() and ocr_path.stat().st_size > 50) or train_path.is_file():
                    continue
                # pypdf empty text-layer: do not thrash; ladder/OCR owns these.
                if needs_marker.is_file():
                    continue
                targets.append(p)
                if len(targets) >= args.limit * 3:
                    break
            if len(targets) >= args.limit * 3:
                break

    for p in targets[: args.limit]:
        scanned += 1
        text, eng = extract_pdf(p)
        engine_used = eng
        at = datetime.now(timezone.utc).isoformat()
        if len(text.strip()) < args.min_chars:
            # Digitally-born vs scanned (pypdf docs): empty layer => OCR handoff marker.
            marker = Path(str(p) + ".needs_ocr.json")
            marker.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "status": "needs_ocr",
                        "reason": "thin_or_empty_text_layer",
                        "chars": len(text.strip()),
                        "engine": eng,
                        "at": at,
                        "path": str(p),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            needs_ocr_paths.append(str(p))
            samples.append(
                f"{p.name[:55]} thin chars={len(text.strip())} eng={eng} -> needs_ocr"
            )
            continue
        body = (
            f"# Extract {p.name}\n\n"
            f"- engine: {eng}\n"
            f"- at: {at}\n"
            f"- chars: {len(text)}\n\n"
            f"```\n{text[:6000]}\n```\n"
        )
        ocr_path = Path(str(p) + ".ocr.md")
        train_path = Path(str(p) + ".train.md")
        ocr_path.write_text(body, encoding="utf-8")
        # Autonomy: also emit .train.md so train-manifest / depth score see the twin.
        train_path.write_text(
            f"# PDF train — {p.name}\n\n- engine: {eng}\n- at: {at}\n\n{text[:12000]}\n",
            encoding="utf-8",
        )
        # Clear stale handoff if digital text now present.
        stale = Path(str(p) + ".needs_ocr.json")
        if stale.is_file():
            try:
                stale.unlink()
            except OSError:
                pass
        written += 1
        samples.append(f"{p.name[:55]} chars={len(text)} eng={eng}")

    if needs_ocr_paths:
        HANDOFF.parent.mkdir(parents=True, exist_ok=True)
        prior: list[str] = []
        if HANDOFF.is_file():
            prior = [
                ln.strip()
                for ln in HANDOFF.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
        merged = list(dict.fromkeys(prior + needs_ocr_paths))
        HANDOFF.write_text("\n".join(merged) + "\n", encoding="utf-8")

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"# PDF extract smoke {datetime.now(timezone.utc).isoformat()}\n\n"
        f"scanned={scanned} written={written} needs_ocr={len(needs_ocr_paths)} "
        f"engine={engine_used}\n\n"
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
                "needs_ocr": len(needs_ocr_paths),
                "samples": samples[:8],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
