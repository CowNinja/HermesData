#!/usr/bin/env python3
"""Build/refresh local twin retrieval cache from k_light + med/navy index.

No LLM. Fast path for demos and future local RAG.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LIGHT = Path(r"D:/HermesData/state/k_light_index.jsonl")
MED = Path(r"D:/HermesData/state/medical_navy_text_index.jsonl")
OUT = Path(r"D:/HermesData/state/twin_retrieval_cache.json")
RECEIPT = Path(r"D:/PhronesisVault/Operations/logs/silo-twin-retrieval-cache-latest.md")

QUERIES = {
    "meds": ["vamc", "meds", "medication", "pharmacy"],
    "PHA": ["pha", "health assessment"],
    "Booksbloom": ["booksbloom", "wswtr", "keepers"],
    "Navy_eval": ["navpers", "eval", "navy"],
    "Family": ["family", "spouse", "children"],
    "DD2808": ["dd2808", "medical examination", "dd2807"],
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(p: Path, limit: int = 50000) -> list[dict]:
    rows = []
    if not p.is_file():
        return rows
    with p.open(encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def score(blob: str, toks: list[str]) -> int:
    return sum(1 for t in toks if t in blob)


def main() -> int:
    light = load_jsonl(LIGHT)
    med = load_jsonl(MED, 80000)
    cache = {"at": utc(), "queries": {}, "stats": {"k_light": len(light), "med_navy": len(med)}}
    for name, toks in QUERIES.items():
        hits = []
        for o in light:
            blob = json.dumps(o).lower()
            sc = score(blob, toks)
            if sc:
                hits.append({"score": sc, "source": "k_light", **{k: o.get(k) for k in ("path", "temporal", "tags", "gold_tier")}})
        for o in med:
            blob = json.dumps(o).lower()
            sc = score(blob, toks)
            if sc >= 2:
                hits.append({"score": sc, "source": "med_navy", "path": o.get("path") or o.get("file")})
        hits.sort(key=lambda x: -int(x.get("score") or 0))
        # dedupe by path
        seen = set()
        uniq = []
        for h in hits:
            p = h.get("path")
            if not p or p in seen:
                continue
            seen.add(p)
            uniq.append(h)
            if len(uniq) >= 8:
                break
        cache["queries"][name] = uniq
    OUT.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    lines = [
        f"# Twin retrieval cache — {cache['at']}",
        "",
        f"k_light **{cache['stats']['k_light']}** · med_navy **{cache['stats']['med_navy']}**",
        "",
        "| Query | Hits |",
        "|-------|-----:|",
    ]
    for name, hits in cache["queries"].items():
        lines.append(f"| {name} | {len(hits)} |")
    lines += ["", f"JSON: `{OUT}`"]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "stats": cache["stats"], "hit_counts": {k: len(v) for k, v in cache["queries"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
