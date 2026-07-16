#!/usr/bin/env python3
"""Interest media catalog-only — DVD/mp4 rips, music libs (not twin training content).

Jeff 2026-07-14: STAR_OF_BETHLEHEM-class media denotes interests; full binary
is NOT training data. Same policy family as music/ISO catalog-only.

Outputs title/path/size manifests under Life-Archive/_media_catalogs.
Personal/family/medical/business audio still lands via heuristics exceptions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
sys.path.insert(0, str(SCRIPTS))
from silo_relevance_heuristics import is_entertainment_media, land_decision  # noqa: E402

OUT_DIR = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Life-Archive\from-g-drive\_media_catalogs"
)
VAULT_NOTE = Path(
    r"D:\PhronesisVault\Operations\Interest-Media-Catalog-Not-Bulk-Ingest-CANONICAL-2026-07-14.md"
)

DEFAULT_ROOTS = [
    Path(r"G:\STAR_OF_BETHLEHEM"),
    Path(r"G:\Old_music"),
    Path(r"G:\Music RIP"),
    Path(r"G:\Z_Jenni_kids_music"),
    Path(r"G:\Old_music_library"),
]

MEDIA_EXT = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".vob",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".wma",
    ".iso",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def catalog_root(root: Path, limit: int = 200_000) -> dict:
    items = []
    ext_c: Counter[str] = Counter()
    n = 0
    if not root.exists():
        return {"root": str(root), "exists": False, "items": 0}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        n += 1
        if n > limit:
            break
        ext = p.suffix.lower()
        ext_c[ext] += 1
        if ext not in MEDIA_EXT and not is_entertainment_media(p):
            continue
        try:
            rel = str(p.relative_to(root))
        except Exception:
            rel = p.name
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        items.append(
            {
                "rel": rel,
                "name": p.name,
                "ext": ext,
                "size": size,
                "decision": land_decision(p),
            }
        )
    return {
        "root": str(root),
        "exists": True,
        "files_scanned": n,
        "media_items": len(items),
        "ext_counts": dict(ext_c.most_common(20)),
        "items": items if len(items) <= 50_000 else items[:50_000],
        "truncated": len(items) > 50_000,
        "cataloged_at": utc(),
        "policy": "interest_catalog_only_not_twin_training_content",
    }


def write_vault_note(summaries: list[dict]) -> None:
    lines = [
        "# Interest media — catalog only (not bulk twin ingest)",
        "",
        f"**Canonical:** 2026-07-14 · Jeff clarity",
        "",
        "## Policy",
        "- Entertainment media (DVD/mp4 rips, commercial video, music libraries) = **catalog title/path/size only**.",
        "- Denotes **interests**, not training content. Do **not** full-copy into silo for RAG/twin.",
        "- Same family as music + ISO catalog-only.",
        "- **Exceptions (still land):** personal/family recordings, medical/Navy audio, Booksbloom conference mixdowns, journals.",
        "- STAR_OF_BETHLEHEM (2× mp4) = interest catalog example.",
        "",
        "## Roots",
    ]
    for s in summaries:
        lines.append(
            f"- `{s.get('root')}` · exists={s.get('exists')} · media={s.get('media_items')} · scanned={s.get('files_scanned')}"
        )
    lines += [
        "",
        "## Code",
        "- `silo_relevance_heuristics.is_entertainment_media` / `land_decision`",
        "- `silo_interest_media_catalog.py`",
        "- `silo_music_catalog_only.py`",
        "",
        "## Links",
        "- [[Operations/Music-Catalog-Not-Bulk-Ingest-CANONICAL-2026-07-13]]",
        "- [[Operations/Relevance-Heuristics-Booksbloom-CANONICAL-2026-07-13]]",
        "- [[Operations/Campaign-Map-Personal-Digital-Silo-CANONICAL-2026-07-12]]",
        "",
    ]
    VAULT_NOTE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_NOTE.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-scan", type=int, default=200_000)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    all_titles = []
    for root in DEFAULT_ROOTS:
        cat = catalog_root(root, limit=args.limit_scan)
        slim = {k: v for k, v in cat.items() if k != "items"}
        summaries.append(slim)
        out = OUT_DIR / f"interest_media_{root.name.replace(' ', '_')}.json"
        out.write_text(json.dumps(cat, indent=2), encoding="utf-8")
        for it in cat.get("items") or []:
            all_titles.append(f"{it.get('size', 0)}\t{it.get('name')}\t{root.name}")
    (OUT_DIR / "interest_media_summary.json").write_text(
        json.dumps({"at": utc(), "roots": summaries}, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "interest_media_titles.txt").write_text(
        "\n".join(all_titles[:100_000]), encoding="utf-8"
    )
    write_vault_note(summaries)
    print(json.dumps({"roots": len(summaries), "out": str(OUT_DIR), "vault": str(VAULT_NOTE)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
