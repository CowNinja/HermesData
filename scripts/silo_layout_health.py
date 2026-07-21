#!/usr/bin/env python3
"""Report silo leaf folders that violate soft layout limits (anti-flat discipline).

Does not move files. Writes Operations/logs/silo-layout-health-latest.md

2026-07-21: --budget-s + registry-first path so orch no longer exit-124 on full K rglob.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
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


def scan_leaf_counts_budgeted(
    root: Path, suffixes: List[str], budget_s: float = 240.0
) -> Tuple[List[Tuple[str, int]], dict]:
    """Count non-sidecar files per directory with wall-clock budget."""
    counts: Dict[str, int] = defaultdict(int)
    n = 0
    t0 = time.time()
    timed_out = False
    if not root.is_dir():
        return [], {"files_seen": 0, "timed_out": False, "mode": "rglob", "elapsed_s": 0}
    for p in root.rglob("*"):
        if time.time() - t0 >= budget_s:
            timed_out = True
            break
        if not p.is_file():
            continue
        if is_sidecar(p.name, suffixes):
            continue
        counts[str(p.parent)] += 1
        n += 1
        if n > 2_000_000:
            break
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    return ranked, {
        "files_seen": n,
        "timed_out": timed_out,
        "mode": "rglob",
        "elapsed_s": round(time.time() - t0, 2),
    }


def scan_from_registry(suffixes: List[str], limit_rows: int = 80000) -> Tuple[List[Tuple[str, int]], dict]:
    """Fast path: folder counts from dest_path parents in ingest_registry."""
    counts: Dict[str, int] = defaultdict(int)
    t0 = time.time()
    if not REG.is_file():
        return [], {"files_seen": 0, "mode": "registry", "error": "no registry"}
    con = sqlite3.connect(str(REG), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        rows = con.execute(
            "SELECT dest_path FROM ingest WHERE dest_path IS NOT NULL AND dest_path != '' "
            "ORDER BY rowid DESC LIMIT ?",
            (limit_rows,),
        ).fetchall()
    finally:
        con.close()
    n = 0
    suf_tuple = tuple(suffixes)
    for (dp,) in rows:
        if not dp:
            continue
        # basename without Path()
        base = dp.replace("\\", "/").rsplit("/", 1)[-1]
        if base.endswith(".meta.json") or ".train." in base:
            continue
        skip = False
        for s in suf_tuple:
            if base.endswith(s) or f"{s}." in base:
                skip = True
                break
        if skip:
            continue
        parent = dp.replace("\\", "/").rsplit("/", 1)[0] if ("/" in dp.replace("\\", "/")) else dp
        counts[parent] += 1
        n += 1
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    return ranked, {
        "files_seen": n,
        "mode": "registry",
        "elapsed_s": round(time.time() - t0, 2),
        "timed_out": False,
        "rows": len(rows),
    }


def registry_summary() -> dict:
    if not REG.exists():
        return {}
    con = sqlite3.connect(str(REG), timeout=30)
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-s", type=float, default=240.0, help="wall-clock budget for FS scan")
    ap.add_argument(
        "--mode",
        choices=("auto", "registry", "rglob"),
        default="auto",
        help="auto=registry first (fast); rglob only if requested",
    )
    ap.add_argument("--limit-rows", type=int, default=120000)
    args = ap.parse_args()

    pol = load_policy()
    lim = int(pol.get("soft_limits", {}).get("max_files_per_leaf_folder", 500))
    suf = list(pol.get("soft_limits", {}).get("exclude_from_count_suffixes") or [])

    scan_meta = {}
    if args.mode in ("auto", "registry"):
        ranked, scan_meta = scan_from_registry(suf, limit_rows=int(args.limit_rows))
        if args.mode == "auto" and not ranked and args.budget_s > 30:
            ranked, scan_meta = scan_leaf_counts_budgeted(SILO, suf, budget_s=min(args.budget_s, 90))
    else:
        ranked, scan_meta = scan_leaf_counts_budgeted(SILO, suf, budget_s=args.budget_s)

    offenders = [(d, c) for d, c in ranked if c > lim][:40]
    top = ranked[:25]

    reg = registry_summary()

    lines = [
        f"# Silo layout health — {utc()}",
        "",
        f"**Soft limit:** {lim} non-sidecar files per folder",
        f"**Scan mode:** {scan_meta.get('mode')} · elapsed {scan_meta.get('elapsed_s')}s · timed_out={scan_meta.get('timed_out')}",
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
        "scan": scan_meta,
        "receipt": str(RECEIPT),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
