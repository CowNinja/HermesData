#!/usr/bin/env python3
"""Build unified Jan + BooksBloom-gold retrieval index for Talk-to-Mom's-writings.

Does NOT dump all 76k pilot files into RAG (noise). Merges:
  1) Jan-Bloom-Author shelf chunks (primary)
  2) BooksBloom gold text on K (WSWTR/Keepers/author paths, .train.md/.txt with gold keys)
  3) Public context stub

One query → one index → talk_to_jan.py
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

JAN_CHUNKS = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author\chunks\jan_chunks.jsonl"
)
UNIFIED = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author\chunks\jan_unified_chunks.jsonl"
)
# Gold text only — antiword/docx extracts live here (avoid huge Documents rglob).
BB_ROOTS = [
    Path(
        r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Projects\from-g-drive\Booksbloom\_gold_extracts"
    ),
]
GOLD_KEYS = (
    "wswtr",
    "who should we then",
    "keepers of the books",
    "keepers",
    "booksbloom",
    "jan bloom",
    "living books",
    "jxn",
    "handout",
    "booksforboys",
    "books for girls",
    "businessbythebooks",
    "_gold_extracts",
)
SKIP = (
    "appdata",
    "chrome",
    "firefox",
    "node_modules",
    "extensions",
    "license.txt",
    "contributors.txt",
    ".context.train.md",
    "/desktop/",
    "\\desktop\\",
    "lastcompat",
    "user data",
    "bank numbers",
    ".url",
    ".jpg.context",
    ".png.context",
    ".jpeg.context",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_gold_path(p: Path) -> bool:
    low = str(p).lower().replace("\\", "/")
    if any(s in low for s in SKIP):
        return False
    # extra junk even under Booksbloom tree
    if any(
        x in low
        for x in (
            "blackviper",
            "/tools/",
            "readme.md",
            "node_modules",
            "package.json",
            ".git/",
            "script-master",
        )
    ):
        return False
    name_ok = any(k in low for k in GOLD_KEYS)
    # require stronger signal for generic booksbloom paths
    if "booksbloom" in low and not any(
        k in low
        for k in (
            "wswtr",
            "keepers",
            "who should",
            "jan bloom",
            "living books",
            "handout",
        )
    ):
        # only keep if filename itself is author-ish
        if not any(
            k in p.name.lower()
            for k in ("wswtr", "keepers", "bloom", "who should", "handout")
        ):
            return False
    return name_ok


def chunk_text(text: str, size: int = 850, overlap: int = 140) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 80:
        return []
    if len(text) <= size:
        return [text]
    out, i = [], 0
    while i < len(text):
        out.append(text[i : i + size])
        i += max(size - overlap, 1)
    return out


def load_jan() -> list[dict]:
    rows = []
    if not JAN_CHUNKS.exists():
        return rows
    with JAN_CHUNKS.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rec["lane"] = "jan_shelf"
            rows.append(rec)
    return rows


def harvest_bb(limit_files: int = 400) -> list[dict]:
    """Harvest gold text only (.md/.txt/.train.md). Prefer _gold_extracts + Documents."""
    rows: list[dict] = []
    n_files = 0
    seen: set[str] = set()
    for root in BB_ROOTS:
        if not root.exists():
            continue
        # Prefer explicit gold extracts first (sorted by size desc via later pass)
        files = [p for p in root.rglob("*") if p.is_file()]
        files.sort(key=lambda p: (0 if "_gold_extracts" in str(p) else 1, -p.stat().st_size if p.exists() else 0))
        for p in files:
            low = str(p).lower()
            if not (
                low.endswith(".train.md")
                or p.suffix.lower() in {".txt", ".md"}
            ):
                continue
            if ".context.train.md" in low or ".context.json" in low:
                continue
            if not is_gold_path(p) and "_gold_extracts" not in low:
                continue
            # Dedup by filename stem-ish
            key = p.name.lower()
            if key in seen:
                continue
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if len(raw) < 100:
                continue
            seen.add(key)
            n_files += 1
            if n_files > limit_files:
                return rows
            # Allow more of large WSWTR extracts
            cap = 400_000 if "wswtr" in low or "2wswtr" in low else 120_000
            for i, ch in enumerate(chunk_text(raw[:cap])):
                rows.append(
                    {
                        "id": f"bb_{p.stem}_{i}_{n_files}",
                        "file": str(p),
                        "source": str(p),
                        "title": p.name,
                        "i": i,
                        "text": ch,
                        "lane": "booksbloom_gold",
                    }
                )
    return rows


def public_stub() -> list[dict]:
    pub = Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Public-Context-2026-07-14.md")
    if not pub.exists():
        return []
    t = pub.read_text(encoding="utf-8", errors="ignore")
    return [
        {
            "id": "public_context_0",
            "file": str(pub),
            "source": str(pub),
            "title": "public BooksBloom context",
            "i": 0,
            "text": t[:3000],
            "lane": "public",
        }
    ]


def build() -> dict:
    jan = load_jan()
    bb = harvest_bb()
    pub = public_stub()
    all_rows = jan + bb + pub
    UNIFIED.parent.mkdir(parents=True, exist_ok=True)
    with UNIFIED.open("w", encoding="utf-8") as f:
        for rec in all_rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    meta = {
        "at": utc(),
        "path": str(UNIFIED),
        "jan_chunks": len(jan),
        "booksbloom_gold_chunks": len(bb),
        "public": len(pub),
        "total": len(all_rows),
        "policy": "unified jan + booksbloom gold only (not full 76k pilot dump)",
    }
    (UNIFIED.parent / "jan_unified_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, indent=2))
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()
    if args.build:
        build()
    else:
        build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
