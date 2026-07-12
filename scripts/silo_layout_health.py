#!/usr/bin/env python3
"""Report silo leaf folders that violate soft layout limits (anti-flat discipline).

Does not move files. Writes Operations/logs/silo-layout-health-latest.md
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

POLICY = Path(r"D:\HermesData\config\silo_layout_policy.json")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-layout-health-latest.md")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def is_sidecar(name: str, suffixes: List[str]) -> bool:
    for s in suffixes:
        if name.endswith(s) or f"{s}." in name:
            return True
    if name.endswith(".meta.json") or ".train." in name:
        return True
    return False


def scan_leaf_counts(root: Path, suffixes: List[str], max_dirs: int = 50000) -> List[Tuple[str, int]]:
    """Count non-sidecar files per directory (any dir that contains files)."""
    counts: Dict[str, int] = defaultdict(int)
    n = 0
    if not root.is_dir():
        return []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if is_sidecar(p.name, suffixes):
            continue
        counts[str(p.parent)] += 1
        n += 1
        if n > 2_000_000:
            break
    return sorted(counts.items(), key=lambda x: -x[1])


def registry_summary() -> dict:
    if not REG.exists():
        return {}
    con = sqlite3.connect(str(REG))
    total = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    by_dom = dict(con.execute("SELECT domain, COUNT(*) FROM ingest GROUP BY domain"))
    inbox = by_dom.get("Core-Personal/_Inbox", 0)
    con.close()
    return {
        "total": total,
        "inbox": inbox,
        "shelved": total - inbox,
        "inbox_pct": round(100 * inbox / total, 1) if total else 0,
        "by_domain": by_dom,
    }


def main() -> int:
    pol = load_policy()
    lim = int(pol.get("soft_limits", {}).get("max_files_per_leaf_folder", 500))
    suf = list(pol.get("soft_limits", {}).get("exclude_from_count_suffixes") or [])

    ranked = scan_leaf_counts(SILO, suf)
    offenders = [(d, c) for d, c in ranked if c > lim][:40]
    top = ranked[:25]

    reg = registry_summary()

    lines = [
        f"# Silo layout health — {utc()}",
        "",
        f"**Soft limit:** {lim} non-sidecar files per folder",
        f"**Folders scanned (with files):** {len(ranked)}",
        f"**Offenders (> limit):** {len(offenders)}",
        "",
        "## Catalog snapshot",
        "",
        f"- registry total: **{reg.get('total')}**",
        f"- inbox: **{reg.get('inbox')}** ({reg.get('inbox_pct')}%)",
        f"- shelved: **{reg.get('shelved')}**",
        "",
        "## Top folders by file count",
        "",
        "| Files | Folder |",
        "|------:|--------|",
    ]
    for d, c in top:
        flag = " ⚠️" if c > lim else ""
        # shorten path
        short = d.replace(str(SILO), "SILO")
        lines.append(f"| {c} | `{short[:100]}`{flag} |")

    lines += [
        "",
        "## Access reminder",
        "",
        "Do **not** browse these in chat. Query `ingest_registry` / ask Hermes.",
        "Layout policy: catalog-first; preserve origin trees; shard if leaf > limit.",
        "",
        "[[Operations/Silo-Order-Layout-and-Ask-Retrieve-CANONICAL-2026-07-12]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")

    out = {
        "ts": utc(),
        "limit": lim,
        "folders_with_files": len(ranked),
        "offenders": len(offenders),
        "top": [{"count": c, "dir": d} for d, c in top[:10]],
        "registry": {k: reg[k] for k in ("total", "inbox", "shelved", "inbox_pct") if k in reg},
        "receipt": str(RECEIPT),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
