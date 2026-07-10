#!/usr/bin/env python3
"""Silo Phase 4 helper: cheap local grunt classify for manifest rows.

Reads a JSONL or text list of paths/snippets, calls grunt_local classify via
HTTP (same path as CLI), writes scores without burning Grok tokens.

Usage:
  python silo_grunt_batch.py --text "Navy 1099 scan PDF medical"
  python silo_grunt_batch.py --jsonl D:\\path\\candidates.jsonl --limit 20
  python silo_grunt_batch.py --paths-file files.txt --limit 10

Does not promote to K: permanent silo - staging/report only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

GRUNT = Path(r"D:\HermesData\scripts\grunt_local.py")
OUT_DEFAULT = Path(r"D:\PhronesisVault\Operations\logs\silo-grunt-batch.jsonl")


def grunt_classify(text: str) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(GRUNT), "classify", "--text", text[:4000]],
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (proc.stdout or "").strip()
    try:
        return {"ok": proc.returncode == 0, "result": json.loads(out) if out.startswith("{") else out}
    except json.JSONDecodeError:
        return {"ok": proc.returncode == 0, "result": out, "stderr": (proc.stderr or "")[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--jsonl", type=Path)
    ap.add_argument("--paths-file", type=Path)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()

    jobs: List[str] = []
    if args.text:
        jobs.append(args.text)
    if args.jsonl and args.jsonl.is_file():
        for line in args.jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                jobs.append(obj.get("text") or obj.get("path") or obj.get("name") or line)
            except json.JSONDecodeError:
                jobs.append(line)
    if args.paths_file and args.paths_file.is_file():
        jobs.extend(
            [ln.strip() for ln in args.paths_file.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        )

    jobs = jobs[: max(1, args.limit)]
    if not jobs:
        print(json.dumps({"error": "no inputs", "hint": "pass --text or --jsonl or --paths-file"}))
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    reports = []
    for i, text in enumerate(jobs):
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "i": i,
            "input": text[:500],
            "grunt": grunt_classify(text),
        }
        reports.append(rec)
        with args.out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    print(json.dumps({"processed": len(reports), "out": str(args.out), "sample": reports[0]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
