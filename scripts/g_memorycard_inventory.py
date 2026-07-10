#!/usr/bin/env python3
"""Lightweight inventory of G: MemoryCard Google Drive sources → vault receipt.

No copies. No deletes. Sample children + counts only (du is too slow on G:).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SOURCES = [
    Path(r"G:\MemoryCard_Backups\Google Drive"),
    Path(r"G:\MemoryCard_Backups\Google Drive(archive)"),
    Path(r"G:\MemoryCard_Backups\Bloom_Jeffrey\Google_Backups"),
    Path(r"G:\MemoryCard_Backups\Bloom_Jeffrey"),
    Path(r"D:\CloudSync\Google-My-Drive"),
]
OUT = Path(r"D:\PhronesisVault\Operations\logs\g-memorycard-sources-inventory-latest.md")
JSON_OUT = Path(r"D:\HermesData\Backups\g-memorycard-sources-inventory.json")


def count_shallow(root: Path, max_depth: int = 2) -> dict:
    files = dirs = 0
    by_ext: dict[str, int] = {}
    if not root.exists():
        return {"exists": False}
    for dirpath, dirnames, filenames in os_walk_limited(root, max_depth):
        dirs += len(dirnames)
        for fn in filenames:
            files += 1
            ext = Path(fn).suffix.lower() or "(none)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
    top = sorted([p.name for p in root.iterdir()], key=str.lower)[:25] if root.is_dir() else []
    return {
        "exists": True,
        "top_children": len(list(root.iterdir())) if root.is_dir() else 0,
        "files_depth_le": files,
        "dirs_depth_le": dirs,
        "ext_top": sorted(by_ext.items(), key=lambda x: -x[1])[:15],
        "sample_names": top,
    }


def os_walk_limited(root: Path, max_depth: int):
    root = root.resolve()
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        rel = Path(dirpath).relative_to(root)
        depth = 0 if str(rel) == "." else len(rel.parts)
        if depth >= max_depth:
            dirnames[:] = []
        yield dirpath, dirnames, filenames


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    data = {"ts": ts, "sources": {}}
    for s in SOURCES:
        info = count_shallow(s, max_depth=2)
        data["sources"][str(s)] = info
        if not info.get("exists"):
            rows.append(f"| `{s}` | MISSING | | |")
            continue
        ext = ", ".join(f"{e}:{n}" for e, n in info["ext_top"][:6])
        rows.append(
            f"| `{s}` | {info['top_children']} top | ~{info['files_depth_le']} files (depth≤2) | {ext} |"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(
            [
                f"# G: MemoryCard / Drive sources inventory — {ts}",
                "",
                "**Purpose:** Primary training data locations for K digital silo drain.",
                "**Rule:** Inventory only — no copy, no purge.",
                "",
                "| Source | Top children | Sample depth | Top extensions |",
                "|--------|--------------|--------------|----------------|",
                *rows,
                "",
                "## Notes",
                "- `.gdoc`/`.gsheet` on disk are often **shortcuts**, not full body text — twin needs export/PDF/text where possible.",
                "- Live Drive: `D:\\CloudSync\\Google-My-Drive` (active mirror).",
                "- Historical: `G:\\MemoryCard_Backups\\Google Drive` + `Google Drive(archive)`.",
                "- Jeff zips/takeout: `Bloom_Jeffrey\\Google_Backups`.",
                "",
                "[[Operations/K-Life-Domain-Taxonomy-CANONICAL-2026-07-10]]",
                "[[Operations/G-to-K-Drain-Assurance-2026-07-10]]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({"md": str(OUT), "json": str(JSON_OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
