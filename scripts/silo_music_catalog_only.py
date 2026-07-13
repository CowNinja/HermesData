#!/usr/bin/env python3
"""Music catalog-only — do NOT bulk-ingest MP3 libraries.

Jeff 2026-07-13: one manifest of songs, not full silo of music.
Suno AI library = future side quest (pin).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Life-Archive\from-g-drive\_music_catalogs")
VAULT_NOTE = Path(r"D:\PhronesisVault\Operations\Music-Catalog-Not-Bulk-Ingest-CANONICAL-2026-07-13.md")

DEFAULT_ROOTS = [
    Path(r"G:\Old_music"),
    Path(r"G:\Music RIP"),
    Path(r"G:\Z_Jenni_kids_music"),
]

AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg", ".wma", ".aiff"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def catalog_root(root: Path, limit: int = 200_000) -> dict:
    tracks = []
    ext_c: Counter[str] = Counter()
    n = 0
    if not root.is_dir():
        return {"root": str(root), "exists": False, "tracks": 0}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        n += 1
        if n > limit:
            break
        ext = p.suffix.lower()
        ext_c[ext] += 1
        if ext in AUDIO_EXT:
            try:
                rel = str(p.relative_to(root))
            except Exception:
                rel = p.name
            tracks.append(
                {
                    "rel": rel,
                    "name": p.name,
                    "ext": ext,
                    "size": p.stat().st_size,
                    "parent": p.parent.name,
                }
            )
    return {
        "root": str(root),
        "exists": True,
        "files_scanned": n,
        "audio_tracks": len(tracks),
        "ext_counts": dict(ext_c.most_common(20)),
        "tracks_sample_or_all": tracks if len(tracks) <= 50000 else tracks[:50000],
        "truncated": len(tracks) > 50000,
        "cataloged_at": utc(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-scan", type=int, default=200_000)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    all_titles = []
    for root in DEFAULT_ROOTS:
        cat = catalog_root(root, limit=args.limit_scan)
        summaries.append({k: v for k, v in cat.items() if k != "tracks_sample_or_all"})
        name = root.name.replace(" ", "_")
        out = OUT_DIR / f"catalog_{name}.json"
        out.write_text(json.dumps(cat, indent=2), encoding="utf-8")
        # lightweight text index for twin
        txt = OUT_DIR / f"catalog_{name}.txt"
        lines = [f"# Music catalog — {root}", f"at {utc()}", f"audio_tracks {cat.get('audio_tracks')}", ""]
        for t in cat.get("tracks_sample_or_all") or []:
            lines.append(t.get("rel") or t.get("name"))
            all_titles.append(t.get("name") or "")
        txt.write_text("\n".join(lines), encoding="utf-8")
        print("wrote", out, "tracks", cat.get("audio_tracks"))

    master = {
        "policy": "catalog_only_no_bulk_mp3_ingest",
        "suno": "pin_future_sidequest_not_found_in_registry_yet",
        "at": utc(),
        "roots": summaries,
        "total_audio": sum(s.get("audio_tracks") or 0 for s in summaries),
    }
    (OUT_DIR / "00_MASTER_MUSIC_CATALOG.json").write_text(
        json.dumps(master, indent=2), encoding="utf-8"
    )
    VAULT_NOTE.write_text(
        f"""# Music: catalog not bulk ingest (CANONICAL 2026-07-13)

**Jeff:** Don't ingest full MP3 libraries. One catalog of songs is enough.
Suno AI library = interesting later; pin side quest (account + songwriting).

## Policy
| Include | Exclude from bulk land |
|---------|------------------------|
| Single catalog JSON/TXT on K | Bulk `.mp3/.flac` libraries |
| Suno exports when found (future) | `G:\\Old_music`, `Music RIP`, kids music as full copy |
| Medical imaging / DNA / docs | — |

## Catalog location
`K:/Phronesis-Sovereign/Personal-Digital-Silo/Core-Personal/Life-Archive/from-g-drive/_music_catalogs/`

## Status
- Generated: {utc()}
- Total audio titles cataloged: {master['total_audio']}
- Suno paths in registry: none yet

## Drain impact
Removed music roots from full-throttle C2 defaults; relevance skip audio bulk.
""",
        encoding="utf-8",
    )
    print(json.dumps(master, indent=2)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
