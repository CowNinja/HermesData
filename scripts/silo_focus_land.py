#!/usr/bin/env python3
"""Focus land: drain only the highest-priority incomplete folder.

Self-improve efficiency: don't re-walk completed trees; put full throttle
on the current top item (Medical→Alex→Booksbloom…).
Caches disk file counts to avoid full-tree scans every tick.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

QUEUE = Path(r"D:\HermesData\config\land_priority_queue.json")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
CACHE = Path(r"D:\HermesData\state\land_folder_disk_cache.json")
SCRIPTS = Path(r"D:\HermesData\scripts")
PY = sys.executable
CACHE_TTL_S = 6 * 3600  # re-count every 6h


def load_cache() -> dict:
    if CACHE.is_file():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, indent=2), encoding="utf-8")


def disk_file_count(root: Path, cache: dict) -> int:
    key = str(root)
    now = time.time()
    ent = cache.get(key) or {}
    if ent.get("n") is not None and (now - float(ent.get("at") or 0)) < CACHE_TTL_S:
        return int(ent["n"])
    n = 0
    for i, fp in enumerate(root.rglob("*")):
        if fp.is_file():
            n += 1
        if i > 250000:
            break
    cache[key] = {"n": n, "at": now}
    save_cache(cache)
    return n


def top_incomplete(threshold: float = 0.97) -> tuple[str | None, dict]:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    items = sorted(
        data.get("land_priority_queue") or [],
        key=lambda x: -int(x.get("priority") or 0),
    )
    cache = load_cache()
    con = sqlite3.connect(str(REG), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        for it in items:
            if it.get("mode") in ("catalog_only", "never", "land_complete"):
                continue
            path = it.get("path")
            if not path or not Path(path).exists():
                continue
            root = Path(path)
            root_n = str(root).replace("/", "\\").rstrip("\\")
            reg_n = con.execute(
                "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?",
                (root_n + "\\" + "%",),
            ).fetchone()[0]
            disk_n = disk_file_count(root, cache)
            pct = (reg_n / disk_n) if disk_n else 1.0
            info = {
                "id": it.get("id"),
                "path": path,
                "priority": it.get("priority"),
                "reg": reg_n,
                "disk": disk_n,
                "pct": round(100 * pct, 1),
            }
            if pct < threshold:
                return path, info
        return None, {"done": True}
    finally:
        con.close()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path, info = top_incomplete()
    print(json.dumps({"focus": info}, indent=2))
    if not path:
        print(json.dumps({"status": "all_priority_complete"}))
        return 0
    if args.dry_run:
        return 0
    cmd = [
        PY,
        str(SCRIPTS / "g_to_k_safe_drain.py"),
        "--apply",
        "--limit",
        str(args.limit),
        "--source",
        path,
    ]
    r = subprocess.run(cmd, cwd=str(SCRIPTS))
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
