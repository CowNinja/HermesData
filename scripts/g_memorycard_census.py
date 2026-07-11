#!/usr/bin/env python3
"""Shallow-to-medium census of MemoryCard Google Drive trees (counts by ext)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOTS = [
    Path(r"G:\MemoryCard_Backups\Google Drive"),
    Path(r"G:\MemoryCard_Backups\Google Drive(archive)"),
]
OUT_MD = Path(r"D:\PhronesisVault\Operations\logs\g-memorycard-census-latest.md")
OUT_JSON = Path(r"D:\HermesData\Backups\g-memorycard-census-latest.json")
# Cap walk for safety on huge trees — sample first MAX files per root then report
MAX_PER_ROOT = 50000


def census_root(root: Path, max_files: int = MAX_PER_ROOT) -> dict:
    if not root.exists():
        return {"exists": False, "path": str(root)}
    ext_c: Counter[str] = Counter()
    files = 0
    bytes_ = 0
    errors = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        try:
            ext = p.suffix.lower() or "(none)"
            ext_c[ext] += 1
            bytes_ += p.stat().st_size
            files += 1
        except Exception:
            errors += 1
        if files >= max_files:
            break
    return {
        "exists": True,
        "path": str(root),
        "files_counted": files,
        "bytes": bytes_,
        "errors": errors,
        "capped": files >= max_files,
        "ext_top": ext_c.most_common(25),
        "ext_all": dict(ext_c),
    }


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    results = [census_root(r) for r in ROOTS]
    total_f = sum(r.get("files_counted") or 0 for r in results)
    total_b = sum(r.get("bytes") or 0 for r in results)
    payload = {"ts": ts, "roots": results, "total_files": total_f, "total_bytes": total_b}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# MemoryCard Google Drive census — {ts}",
        "",
        f"**Total files counted:** {total_f} · **Bytes:** {total_b:,}",
        "",
    ]
    for r in results:
        lines.append(f"## `{r.get('path')}`")
        if not r.get("exists"):
            lines.append("MISSING")
            continue
        lines.append(
            f"- files={r['files_counted']} · bytes={r['bytes']:,} · capped={r['capped']} · errors={r['errors']}"
        )
        lines.append("")
        lines.append("| Ext | Count |")
        lines.append("|-----|------:|")
        for ext, n in r.get("ext_top") or []:
            lines.append(f"| `{ext}` | {n} |")
        lines.append("")
    lines.append("[[Operations/G-MemoryCard-Ingestion-Trial-Five-Actions-2026-07-10]]")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"total_files": total_f, "total_bytes": total_b, "md": str(OUT_MD)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
