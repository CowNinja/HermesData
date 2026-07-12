#!/usr/bin/env python3
"""Write simple 00-INDEX.md for major silo domain shelves (vault-index-maps pattern)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
DOMAINS = [
    "Medical-Records",
    "Navy-Service",
    "Core-Personal/Family",
    "Core-Personal/Friends",
    "Core-Personal/Finance",
    "Core-Personal/Projects",
    "Core-Personal/Education",
    "Core-Personal/Career",
    "Core-Personal/Life-Archive",
    "Core-Personal/Spiritual",
    "Core-Personal/_Inbox",
    "Digital-Footprint",
    "Life-Archive",
    "_Fused",
]


def index_shelf(rel: str) -> dict:
    root = SILO / rel
    if not root.is_dir():
        return {"rel": rel, "ok": False, "reason": "missing"}
    files = 0
    meta = 0
    ocr = 0
    ctx = 0
    samples = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.endswith(".meta.json"):
            meta += 1
            continue
        if p.name.endswith(".ocr.md"):
            ocr += 1
            continue
        if p.name.endswith(".context.json"):
            ctx += 1
            continue
        if p.name.startswith("00-INDEX"):
            continue
        files += 1
        if len(samples) < 12:
            try:
                samples.append(str(p.relative_to(root)).replace("\\", "/")[:80])
            except Exception:
                samples.append(p.name[:80])
    lines = [
        f"# {rel}",
        "",
        f"_Auto index — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "**Access:** catalog-first — `python D:/HermesData/scripts/silo_retrieve.py \"…\"` or ask Hermes.",
        "**Layout:** nested `from-g-drive/<origin tree>/` (copy directory structure; open taxonomy).",
        "",
        f"- files (approx): **{files}**",
        f"- .meta.json: **{meta}**",
        f"- .context.json: **{ctx}**",
        f"- .ocr.md: **{ocr}**",
        "",
        "## Sample paths (nested)",
        "",
    ]
    for s in samples:
        lines.append(f"- `{s}`")
    lines.append("")
    lines.append("See ingest registry + `.meta.json` for full provenance.")
    (root / "00-INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    return {"rel": rel, "ok": True, "files": files, "meta": meta, "ocr": ocr, "ctx": ctx}


def main() -> int:
    results = [index_shelf(d) for d in DOMAINS]
    print(json.dumps({"results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
