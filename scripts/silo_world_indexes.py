#!/usr/bin/env python3
"""Write lightweight silo WORLD index (top-level shelves only — fast).

Pairs with silo_domain_indexes.py (deep per-domain). K-light cron calls both.
2026-07-18: created so K-Light no longer reports missing_script for world leg.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
OUT = SILO / "00-WORLD-INDEX.md"
# Cap per-shelf immediate children count (no deep rglob — domain job owns depth).
MAX_CHILDREN_LIST = 40


def shelf_row(p: Path) -> dict:
    if not p.is_dir():
        return {"name": p.name, "ok": False, "reason": "not_dir"}
    files = 0
    dirs = 0
    samples: list[str] = []
    try:
        for child in p.iterdir():
            try:
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    dirs += 1
                    if len(samples) < MAX_CHILDREN_LIST:
                        samples.append(child.name + "/")
                elif child.is_file():
                    files += 1
                    if len(samples) < MAX_CHILDREN_LIST:
                        samples.append(child.name)
            except OSError:
                continue
    except OSError as e:
        return {"name": p.name, "ok": False, "reason": str(e)[:120]}
    return {
        "name": p.name,
        "ok": True,
        "dirs": dirs,
        "files": files,
        "samples": samples[:12],
    }


def main() -> int:
    if not SILO.is_dir():
        print(json.dumps({"ok": False, "reason": "K_missing", "silo": str(SILO)}))
        return 1

    shelves = []
    try:
        entries = sorted(
            [p for p in SILO.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda x: x.name.lower(),
        )
    except OSError as e:
        print(json.dumps({"ok": False, "reason": str(e)[:200]}))
        return 1

    for p in entries:
        # Skip obvious bulk noise dirs if any naming convention
        shelves.append(shelf_row(p))

    ok_n = sum(1 for s in shelves if s.get("ok"))
    lines = [
        "# Personal Digital Silo — World Index",
        "",
        f"_Auto world index — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "**Access:** catalog-first — `python D:/HermesData/scripts/silo_retrieve.py \"…\"` or ask Hermes.",
        "**Depth:** domain shelves get `00-INDEX.md` from `silo_domain_indexes.py`.",
        "",
        f"- top-level shelves: **{len(shelves)}** (ok={ok_n})",
        "",
        "## Shelves",
        "",
        "| Shelf | Dirs | Files (top) | Sample |",
        "|-------|------|-------------|--------|",
    ]
    for s in shelves:
        if not s.get("ok"):
            lines.append(f"| `{s.get('name')}` | — | — | {s.get('reason', 'err')} |")
            continue
        sample = ", ".join(f"`{x}`" for x in (s.get("samples") or [])[:4]) or "—"
        lines.append(
            f"| `{s['name']}` | {s.get('dirs', 0)} | {s.get('files', 0)} | {sample} |"
        )
    lines += [
        "",
        "See domain `00-INDEX.md` files + ingest registry for provenance.",
        "",
    ]
    try:
        OUT.write_text("\n".join(lines), encoding="utf-8")
    except OSError as e:
        print(json.dumps({"ok": False, "reason": f"write_failed:{e}", "path": str(OUT)}))
        return 1

    payload = {
        "ok": True,
        "silo": str(SILO),
        "out": str(OUT),
        "shelves": len(shelves),
        "ok_shelves": ok_n,
        "seal": "2026-07-18-world-index",
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
