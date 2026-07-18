#!/usr/bin/env python3
"""Chunk Jan author text shelf + keyword retrieve (quality-filtered)."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHELF = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author"
)
CHUNKS = SHELF / "chunks" / "jan_chunks.jsonl"
UNIFIED = SHELF / "chunks" / "jan_unified_chunks.jsonl"

JUNK = re.compile(
    r"(times new roman|mergeformat|BLANK PAGE|DLB,MAI|AlliS|hyperlink\s+\\\"http)",
    re.I,
)


def clean_body(raw: str) -> str:
    if raw.startswith("SOURCE:"):
        lines = raw.splitlines()
        try:
            bi = lines.index("")
            raw = "\n".join(lines[bi + 1 :])
        except ValueError:
            pass
    # drop junk lines
    keep = []
    for ln in raw.splitlines():
        s = ln.strip()
        if len(s) < 8:
            continue
        if JUNK.search(s) and sum(c.isalpha() for c in s) < 40:
            continue
        keep.append(s)
    return re.sub(r"\s+", " ", "\n".join(keep)).strip()


def chunk_text(text: str, size: int = 850, overlap: int = 140) -> list[str]:
    if len(text) <= size:
        return [text] if len(text) > 60 else []
    out = []
    i = 0
    while i < len(text):
        piece = text[i : i + size]
        if len(piece) > 60 and sum(c.isalpha() for c in piece) / max(len(piece), 1) > 0.45:
            out.append(piece)
        i += max(size - overlap, 1)
    return out


def build_index() -> int:
    """Chunk text/ and text_wpd/ shelves into jan_chunks.jsonl."""
    text_dirs = [SHELF / "text", SHELF / "text_wpd"]
    CHUNKS.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    seen_body_prefix: set[str] = set()
    with CHUNKS.open("w", encoding="utf-8") as f:
        for text_dir in text_dirs:
            if not text_dir.is_dir():
                continue
            for p in sorted(text_dir.glob("*.txt")):
                try:
                    raw = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if len(raw) < 200:
                    continue  # skip thin failed WPD shells
                source = ""
                method = ""
                if raw.startswith("SOURCE:"):
                    lines = raw.splitlines()
                    source = lines[0].replace("SOURCE:", "").strip()
                    for ln in lines[1:8]:
                        if ln.startswith("METHOD:"):
                            method = ln.replace("METHOD:", "").strip()
                body = clean_body(raw)
                if len(body) < 120:
                    continue
                # light dedup across text/ vs text_wpd near-duplicates
                prefix = body[:240].lower()
                if prefix in seen_body_prefix:
                    continue
                seen_body_prefix.add(prefix)
                lane = "jan_wpd" if text_dir.name == "text_wpd" else "jan_shelf"
                for i, ch in enumerate(chunk_text(body)):
                    rec = {
                        "id": f"{p.stem}_{i}",
                        "file": str(p),
                        "source": source or str(p),
                        "title": Path(source).name if source else p.name,
                        "i": i,
                        "text": ch,
                        "lane": lane,
                        "method": method,
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
    print(json.dumps({"chunks": n, "path": str(CHUNKS), "dirs": [str(d) for d in text_dirs]}))
    return n


def retrieve(query: str, k: int = 8) -> list[dict]:
    path = UNIFIED if UNIFIED.exists() else CHUNKS
    if not path.exists():
        return []
    q = set(re.findall(r"[a-z0-9']{3,}", query.lower()))
    ql = query.lower()
    scored = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            t = rec.get("text", "")
            tl = t.lower()
            words = set(re.findall(r"[a-z0-9']{3,}", tl))
            score = float(len(q & words))
            for phrase, boost in (
                ("who should we then", 5),
                ("keepers of the books", 4),
                ("mighty whitey", 6),
                ("thrift", 3),
                ("meteor", 4),
                ("niagara", 4),
                ("dedication", 2),
                ("gary", 2),
                ("font", 2),
                ("booksbloom", 3),
                ("homeschool", 2),
                ("conference", 2),
                ("new book", 2),
                ("merge", 1),
            ):
                if phrase in ql and phrase in tl:
                    score += boost
            # slight boost for jan shelf over incidental bb noise
            if rec.get("lane") == "jan_shelf":
                score += 0.5
            if score > 0:
                scored.append((score, rec))
    scored.sort(key=lambda x: -x[0])
    out = []
    seen_src = set()
    for sc, rec in scored:
        src = rec.get("source") or ""
        key = Path(src).name
        if key in seen_src and len(out) >= max(k // 2, 3):
            continue
        seen_src.add(key)
        out.append(rec)
        if len(out) >= k:
            break
    if len(out) < k:
        for sc, rec in scored:
            if rec not in out:
                out.append(rec)
            if len(out) >= k:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--query", default="")
    ap.add_argument("-k", type=int, default=8)
    args = ap.parse_args()
    if args.build:
        build_index()
    if args.query:
        print(json.dumps({"hits": retrieve(args.query, args.k)}, indent=2)[:10000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
