#!/usr/bin/env python3
"""Full rebuild of Jan Bloom author corpus — clean extract + inventory.

Priority: WSWTR folder (all files), Keepers handouts, known top-level WSWTR docs.
.wpd: improved binary text recovery (WordPerfect is messy; best-effort).
.doc: antiword when available, else strings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SHELF = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author"
)
WSWTR = Path(
    r"G:\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Documents\WSWTR"
)
HANDOUTS = Path(
    r"G:\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Documents\00-BooksBloom Handouts"
)
DOCS = Path(r"G:\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Documents")
DOWNLOADS = Path(
    r"G:\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Downloads"
)

# Reject non-Jan academic noise even if under Documents
REJECT_NAME = re.compile(
    r"(psycholog|pyc\s*437|engl\.?\s*191|strickland|arent|jenni.?d\.?\s*bloom|"
    r"english-book-chapter|jenni-january|abnormal)",
    re.I,
)

ENGLISH_HINTS = set(
    """
    the and for with that this from book books author authors read reading
    children child library home who should then keepers bloom jan gary
    family stories living great good volume chapter dedication conference
    bookstore thrift shelves parents young adult adults
    """.split()
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_id(path: Path) -> str:
    h = hashlib.sha1(str(path).encode("utf-8", errors="ignore")).hexdigest()[:10]
    safe = re.sub(r"[^\w.\-]+", "_", path.stem)[:72]
    return f"{safe}__{h}"


def is_reject(path: Path) -> bool:
    return bool(REJECT_NAME.search(path.name)) or path.name.startswith("~$")


def collect_sources() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        if not p.is_file() or is_reject(p):
            return
        k = str(p).lower()
        if k in seen:
            return
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".zip"}:
            return
        seen.add(k)
        out.append(p)

    if WSWTR.exists():
        for p in WSWTR.iterdir():
            add(p)
    if HANDOUTS.exists():
        for p in HANDOUTS.rglob("*"):
            if p.is_file() and re.search(r"keepers|wswtr|who should", p.name, re.I):
                add(p)
    if DOCS.exists():
        for p in DOCS.iterdir():
            if p.is_file() and re.search(
                r"wswtr|keepers of the books|who should", p.name, re.I
            ):
                add(p)
    if DOWNLOADS.exists():
        for p in DOWNLOADS.iterdir():
            if p.is_file() and re.search(r"wswtr|keepers|who should", p.name, re.I):
                if p.suffix.lower() != ".zip":
                    add(p)
    return sorted(out, key=lambda p: p.name.lower())


def score_line(s: str) -> float:
    s = s.strip()
    if len(s) < 20:
        return 0.0
    letters = sum(c.isalpha() for c in s)
    ratio = letters / max(len(s), 1)
    if ratio < 0.55:
        return 0.0
    words = re.findall(r"[a-zA-Z']{3,}", s.lower())
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in ENGLISH_HINTS)
    # penalize font/table garbage
    if "times new roman" in s.lower() or "mergeformat" in s.lower():
        return 0.0
    return ratio + 0.15 * hits + min(len(words), 40) * 0.01


def strings_extract(path: Path, limit: int = 400_000) -> str:
    data = path.read_bytes()
    candidates: list[str] = []

    # ASCII runs
    cur = bytearray()
    for b in data:
        if 32 <= b < 127 or b in (9, 10, 13):
            cur.append(b)
        else:
            if len(cur) >= 12:
                candidates.append(cur.decode("ascii", "ignore"))
            cur = bytearray()
    if len(cur) >= 12:
        candidates.append(cur.decode("ascii", "ignore"))

    # UTF-16LE runs (common in .doc; sometimes WP leftovers)
    wordy = re.compile(r"[A-Za-z][A-Za-z0-9\s\.,;:!?\-()/'\"+]{15,}")
    try:
        u = data.decode("utf-16le", errors="ignore")
        for m in wordy.finditer(u):
            candidates.append(m.group(0))
    except Exception:
        pass

    # WordPerfect-ish: many WP files have extended ASCII text
    try:
        u8 = data.decode("latin-1", errors="ignore")
        for m in wordy.finditer(u8):
            candidates.append(m.group(0))
    except Exception:
        pass

    scored: list[tuple[float, str]] = []
    seen_l: set[str] = set()
    for block in candidates:
        for ln in re.split(r"[\r\n]+", block):
            s = re.sub(r"\s+", " ", ln).strip()
            if s.lower() in seen_l:
                continue
            sc = score_line(s)
            if sc >= 0.65:
                seen_l.add(s.lower())
                scored.append((sc, s))

    scored.sort(key=lambda x: -x[0])
    # keep order of appearance among top-scoring by re-scanning
    keep = {s for _, s in scored[:8000]}
    ordered = []
    for block in candidates:
        for ln in re.split(r"[\r\n]+", block):
            s = re.sub(r"\s+", " ", ln).strip()
            if s in keep and s not in ordered:
                ordered.append(s)
    text = "\n".join(ordered)
    return text[:limit]


def antiword_doc(path: Path) -> str | None:
    try:
        r = subprocess.run(
            ["antiword", "-m", "UTF-8.txt", str(path)],
            capture_output=True,
            timeout=120,
        )
        out = (r.stdout or b"").decode("utf-8", errors="ignore").strip()
        if len(out) > 200:
            return out
        # fallback default
        r2 = subprocess.run(
            ["antiword", str(path)], capture_output=True, timeout=120
        )
        out2 = (r2.stdout or b"").decode("utf-8", errors="ignore").strip()
        return out2 if len(out2) > 200 else None
    except Exception:
        return None


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    t = re.sub(r"<[^>]+>", " ", xml)
    return re.sub(r"\s+", " ", t).strip()


def extract_pdf(path: Path) -> str:
    try:
        import pypdf

        r = pypdf.PdfReader(str(path))
        return "\n".join((pg.extract_text() or "") for pg in r.pages)
    except Exception as e:
        return f"[pdf error: {e}]"


def extract_file(path: Path) -> tuple[str, str]:
    suf = path.suffix.lower()
    if suf == ".docx":
        return extract_docx(path), "docx"
    if suf == ".pdf":
        return extract_pdf(path), "pdf"
    if suf in {".txt", ".md", ".rtf"}:
        return path.read_text(encoding="utf-8", errors="ignore"), suf
    if suf == ".doc":
        aw = antiword_doc(path)
        if aw:
            return aw, "antiword"
        return strings_extract(path), "strings_doc"
    if suf == ".wpd":
        # higher limit for big printbooks
        lim = 600_000 if path.stat().st_size > 1_000_000 else 300_000
        return strings_extract(path, limit=lim), "strings_wpd"
    return "", "skip"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="wipe text/meta before extract")
    args = ap.parse_args()

    text_dir = SHELF / "text"
    meta_dir = SHELF / "meta"
    chunks_dir = SHELF / "chunks"
    SHELF.mkdir(parents=True, exist_ok=True)
    if args.clean:
        if text_dir.exists():
            shutil.rmtree(text_dir)
        if meta_dir.exists():
            shutil.rmtree(meta_dir)
    text_dir.mkdir(exist_ok=True)
    meta_dir.mkdir(exist_ok=True)
    chunks_dir.mkdir(exist_ok=True)

    sources = collect_sources()
    inv_items = []
    extracted = 0
    chars = 0
    methods: dict[str, int] = {}

    for p in sources:
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        rec = {
            "path": str(p),
            "name": p.name,
            "ext": p.suffix.lower(),
            "size": size,
        }
        inv_items.append(rec)
        if p.suffix.lower() not in {
            ".doc",
            ".docx",
            ".pdf",
            ".wpd",
            ".txt",
            ".md",
            ".rtf",
        }:
            continue
        try:
            body, method = extract_file(p)
        except Exception as e:
            body, method = "", f"err:{e}"
        methods[method] = methods.get(method, 0) + 1
        if not body or len(body.strip()) < 80:
            rec["extract"] = "empty"
            continue
        fid = file_id(p)
        outp = text_dir / f"{fid}.txt"
        header = (
            f"SOURCE: {p}\nMETHOD: {method}\nEXTRACTED: {utc()}\n"
            f"TITLE_HINT: {p.name}\nCHARS: {len(body)}\n\n"
        )
        outp.write_text(header + body, encoding="utf-8", errors="ignore")
        meta = {
            "source": str(p),
            "text": str(outp),
            "method": method,
            "chars": len(body),
            "at": utc(),
            "title_hint": p.name,
        }
        (meta_dir / f"{fid}.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        extracted += 1
        chars += len(body)
        rec["extract"] = method
        rec["chars"] = len(body)

    inv = {
        "at": utc(),
        "count_sources": len(sources),
        "extracted": extracted,
        "chars": chars,
        "methods": methods,
        "items": inv_items,
    }
    (SHELF / "inventory.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")
    (SHELF / "00-INDEX.md").write_text(
        "\n".join(
            [
                "# Jan Bloom Author — corpus shelf",
                "",
                f"**Updated:** {utc()}",
                f"**Sources:** {len(sources)} · **Extracted:** {extracted} · **Chars:** {chars}",
                f"**Methods:** {methods}",
                "",
                "Tags: `jan-author` `wswtr` `keepers` `booksbloom`",
                "",
                "Goal: [[Operations/GOAL-Talk-to-Jan-Writing-Agent-2026-07-14]]",
                "SOUL: [[Operations/SOUL-Jan-Library-Agent-2026-07-14]]",
                "CLI: `python D:/HermesData/scripts/talk_to_jan.py \"…\"`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({k: inv[k] for k in ("count_sources", "extracted", "chars", "methods")}, indent=2))
    print("shelf", str(SHELF))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
