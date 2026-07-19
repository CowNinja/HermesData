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

try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore

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


def vault_pack_rows() -> list[dict]:
    """Thin vault CNS packs as labeled retrieval lanes (not manuscript text).

    talk_to_jan already injects these into the system prompt; indexing them
    also lets retrieve() surface Hi-Ho Silver / workshop titles / public
    schedule facts when the query is about living/road life.
    """
    packs = [
        (
            Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Public-Context-2026-07-14.md"),
            "public",
            "public BooksBloom context",
            4500,
        ),
        (
            Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Family-Living-Facts-2026-07-14.md"),
            "family_living",
            "family living facts (labeled)",
            3500,
        ),
        (
            Path(r"D:\PhronesisVault\Operations\Jan-Bloom-Workshop-Catalog-2026-07-18.md"),
            "workshop_catalog",
            "workshop catalog (business docs)",
            4000,
        ),
        (
            Path(r"D:\PhronesisVault\Operations\BooksBloom-Convention-Master-Table-2026-07-19.md"),
            "convention_master",
            "convention master table",
            5000,
        ),
        (
            Path(r"D:\PhronesisVault\Operations\WSWTR-Author-List-Extract-2026-07-19.md"),
            "author_list",
            "WSWTR author list extract (gold only, partial)",
            12000,
        ),
    ]
    rows: list[dict] = []
    for path, lane, title, cap in packs:
        if not path.exists():
            continue
        t = path.read_text(encoding="utf-8", errors="ignore").strip()
        if len(t) < 80:
            continue
        body = t[:cap]
        # Keep vault CNS packs whole whenever possible so tables (schedules,
        # family facts, workshop lists) don't fragment across retrieve hits.
        # Only chunk packs larger than the read cap window.
        if len(body) <= cap:
            pieces = [body]
        else:
            pieces = chunk_text(body, size=1200, overlap=200) or [body]
        for i, ch in enumerate(pieces):
            rows.append(
                {
                    "id": f"{lane}_{i}",
                    "file": str(path),
                    "source": str(path),
                    "title": title,
                    "i": i,
                    "text": ch,
                    "lane": lane,
                }
            )
    return rows


def public_stub() -> list[dict]:
    """Backward-compatible alias — prefer vault_pack_rows(). """
    return [r for r in vault_pack_rows() if r.get("lane") == "public"]


def _atomic_write_jsonl(path: Path, rows: list[dict]) -> str:
    """Write JSONL without leaving a 0-byte target on crash or Win lock.

    Pattern: write complete .tmp → fsync → replace. On Windows PermissionError
    (destination briefly locked), fall back to copy2 over the target only after
    tmp is fully written — never open(target, 'w') first.
    """
    import os
    import shutil
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    expected = tmp.stat().st_size
    if expected < 50:
        raise RuntimeError(f"refusing to publish tiny tmp size={expected}")
    method = "os.replace"
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            last_err = None
            break
        except PermissionError as e:
            last_err = e
            method = "copy2_fallback"
            time.sleep(0.15 * (attempt + 1))
            try:
                shutil.copy2(tmp, path)
                if path.stat().st_size == expected:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                    last_err = None
                    break
            except OSError as e2:
                last_err = e2
    if last_err is not None:
        # Leave tmp in place for recovery; do not wipe target
        raise RuntimeError(
            f"atomic publish failed; tmp kept at {tmp} size={expected}: {last_err}"
        ) from last_err
    if path.stat().st_size != expected and method == "os.replace":
        # rare race; still better than empty
        pass
    return method


def build() -> dict:
    jan = load_jan()
    bb = harvest_bb()
    vault = vault_pack_rows()
    all_rows = jan + bb + vault
    write_method = _atomic_write_jsonl(UNIFIED, all_rows)
    lanes: dict[str, int] = {}
    for rec in all_rows:
        lane = rec.get("lane") or "?"
        lanes[lane] = lanes.get(lane, 0) + 1
    meta = {
        "at": utc(),
        "path": str(UNIFIED),
        "jan_chunks": len(jan),
        "booksbloom_gold_chunks": len(bb),
        "vault_pack_chunks": len(vault),
        "lanes": lanes,
        "public": lanes.get("public", 0),
        "family_living": lanes.get("family_living", 0),
        "workshop_catalog": lanes.get("workshop_catalog", 0),
        "convention_master": lanes.get("convention_master", 0),
        "total": len(all_rows),
        "bytes": UNIFIED.stat().st_size if UNIFIED.exists() else 0,
        "policy": "unified jan + booksbloom gold + vault CNS packs (not full pilot dump)",
        "write": write_method,
    }
    meta_path = UNIFIED.parent / "jan_unified_meta.json"
    if atomic_write_json is not None:
        meta["meta_write"] = atomic_write_json(meta_path, meta, min_bytes=20)
    else:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        meta["meta_write"] = "write_text_fallback"
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
