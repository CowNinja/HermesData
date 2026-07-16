#!/usr/bin/env python3
"""Twin retrieval demos — prove silo value for day-to-day asks.

Post-OCR: more queries + temporal flags from train.meta / k_light_index.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:/HermesData/scripts")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-twin-retrieval-demo-latest.md")
INDEX = Path(r"D:/HermesData/state/medical_navy_text_index.jsonl")
LIGHT = Path(r"D:/HermesData/state/k_light_index.jsonl")

DEMOS = [
    ("meds_current", "VAMC meds"),
    ("PHA", "PHA"),
    ("Booksbloom", "booksbloom"),
    ("Navy_eval", "NAVPERS eval"),
    ("Family", "Family"),
    ("DD2808", "DD2808 medical examination"),
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


def light_hits(q: str, limit: int = 3) -> list:
    if not LIGHT.is_file():
        return []
    toks = [t for t in re.split(r"\s+", q.lower()) if len(t) >= 3]
    hits = []
    with LIGHT.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            blob = json.dumps(o).lower()
            if any(t in blob for t in toks[:2]):
                hits.append(o)
            if len(hits) >= limit:
                break
    return hits


def temporal_note(path: str) -> str:
    meta = Path(str(path) + ".train.meta.json")
    if meta.is_file():
        try:
            m = json.loads(meta.read_text(encoding="utf-8", errors="replace"))
            t = m.get("temporal") or "unknown"
            tags = ",".join(m.get("tags") or [])
            return f"temporal={t} tags={tags}"
        except Exception:
            pass
    return ""


def main() -> int:
    lines = [f"# Twin retrieval demo — {utc()}", ""]
    report = {"at": utc(), "demos": []}
    summary = {}
    for name, q in DEMOS:
        cat = retrieve(q, 5)
        idx = index_hits(q, 3)
        light = light_hits(q, 3)
        hits = (cat or {}).get("hits") or []
        report["demos"].append(
            {
                "name": name,
                "query": q,
                "catalog_n": len(hits),
                "index_n": len(idx),
                "light_n": len(light),
            }
        )
        summary[name] = len(hits)
        lines.append(f"## {name} — `{q}`")
        if hits:
            for h in hits[:5]:
                p = h.get("path") or ""
                tn = temporal_note(p)
                extra = f" · {tn}" if tn else ""
                lines.append(
                    f"- **{h.get('domain')}** · `{Path(p).name}` · {h.get('process_status')}{extra}"
                )
        else:
            lines.append("- _(no catalog path hits)_")
        if idx:
            lines.append(f"- med/navy index hits: **{len(idx)}**")
        if light:
            lines.append(
                f"- k-light hits: **{len(light)}** "
                f"(e.g. temporal={light[0].get('temporal')})"
            )
        lines.append("")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {"receipt": str(RECEIPT), "demo_count": len(DEMOS), "summary": summary},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
