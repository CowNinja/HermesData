#!/usr/bin/env python3
"""Twin retrieval demos — prove silo value for day-to-day asks.

Runs catalog-first retrieve for fixed demo queries; optional text hit
from medical_navy index / .ocr.md sidecars.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-twin-retrieval-demo-latest.md")
INDEX = Path(r"D:/HermesData/state/medical_navy_text_index.jsonl")

DEMOS = [
    ("meds", "VAMC meds"),
    ("PHA", "PHA"),
    ("Booksbloom", "booksbloom"),
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def retrieve(q: str, limit: int = 5) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "silo_retrieve.py"), "--limit", str(limit), q],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return {"raw": (r.stdout or "")[:500], "error": r.stderr[:200] if r.stderr else None}


def index_hits(q: str, limit: int = 3) -> list:
    if not INDEX.is_file():
        return []
    toks = [t for t in re.split(r"\s+", q.lower()) if len(t) >= 3]
    hits = []
    with INDEX.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            blob = json.dumps(o).lower()
            if all(t in blob for t in toks[:3]):
                hits.append(o)
            if len(hits) >= limit:
                break
    return hits


def main() -> int:
    lines = [f"# Twin retrieval demo — {utc()}", ""]
    report = {"at": utc(), "demos": []}
    for name, q in DEMOS:
        cat = retrieve(q, 5)
        idx = index_hits(q, 3)
        report["demos"].append({"name": name, "query": q, "catalog": cat, "index_n": len(idx)})
        lines.append(f"## {name} — `{q}`")
        hits = (cat or {}).get("hits") or []
        if hits:
            for h in hits[:5]:
                lines.append(f"- **{h.get('domain')}** · `{Path(h.get('path') or '').name}` · {h.get('process_status')}")
        else:
            lines.append("- _(no catalog path hits)_")
        if idx:
            lines.append(f"- index sidecar hits: **{len(idx)}**")
        lines.append("")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "demo_count": len(DEMOS), "summary": [
        {d["name"]: len((d["catalog"] or {}).get("hits") or []) for d in report["demos"]}
    ]}, indent=2))
    return 0


if __name__ == "__main__":
    from pathlib import Path
    raise SystemExit(main())
