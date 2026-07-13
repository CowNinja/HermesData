#!/usr/bin/env python3
"""Everything / ES search harness.

voidtools Everything indexes all drives. CLI tool is usually es.exe
(not always installed next to Everything.exe).

Usage:
  python everything_search.py "suno"
  python everything_search.py --status
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

CANDIDATES = [
    Path(r"C:\Program Files\Everything\es.exe"),
    Path(r"C:\Program Files (x86)\Everything\es.exe"),
    Path(r"D:\Tools\Everything\es.exe"),
    Path(r"D:\Everything\es.exe"),
]
EVERYTHING_GUI = Path(r"C:\Program Files\Everything\Everything.exe")


def find_es() -> Path | None:
    which = shutil.which("es") or shutil.which("es.exe")
    if which:
        return Path(which)
    for p in CANDIDATES:
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    es = find_es()
    status = {
        "everything_gui": str(EVERYTHING_GUI) if EVERYTHING_GUI.is_file() else None,
        "es_cli": str(es) if es else None,
        "ready_for_agent_search": bool(es),
        "note": "Install voidtools ES (Everything command-line) for agent harness; GUI alone is not scriptable the same way.",
    }
    if args.status or not args.query:
        print(json.dumps(status, indent=2))
        return 0 if es else 2
    assert es is not None
    # es.exe query -n limit
    cmd = [str(es), "-n", str(args.limit), args.query]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    print(r.stdout or r.stderr)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
