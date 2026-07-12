#!/usr/bin/env python3
"""Compound folder dossiers — neighborhood context for every origin directory.

For each unique parent folder on G: (from registry source_path), write:
  D:\\HermesData\\state\\folder_dossiers\\<hash>.json
  and optionally K-side dossier next to first seen child.

Fields: path, parents, siblings, file_count, sample_names, domain_votes,
entity hits, date hints, summary blob for classify/enrich.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
ENTITY = Path(r"D:\HermesData\config\entity_context.json")
OUT = Path(r"D:\HermesData\state\folder_dossiers")
LOG = Path(r"D:\PhronesisVault\Operations\logs\folder-dossiers-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_entities() -> list[dict]:
    try:
        d = json.loads(ENTITY.read_text(encoding="utf-8"))
        return list(d.get("people") or []) + list(d.get("orgs") or [])
    except Exception:
        return []


def entity_hits(blob: str, entities: list[dict]) -> list[str]:
    low = blob.lower()
    hits = []
    for pe in entities:
        names = list(pe.get("names") or []) + list(pe.get("aliases") or [])
        if pe.get("canonical"):
            names.append(str(pe["canonical"]))
        for n in names:
            n = (n or "").strip()
            if len(n) < 4:
                continue
            if n.lower() in low:
                hits.append(str(pe.get("canonical") or n))
                break
    return sorted(set(hits))[:20]


def date_hints(blob: str) -> list[str]:
    pats = [
        r"\b(20\d{2}-\d{2}-\d{2})\b",
        r"\b(20\d{2}/\d{2}/\d{2})\b",
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2})\b",
        r"\b(20\d{2})\b",
    ]
    found = []
    for p in pats:
        found.extend(re.findall(p, blob, re.I))
    # flatten tuples
    out = []
    for f in found:
        out.append(f if isinstance(f, str) else f[0])
    return sorted(set(out))[:15]


def folder_key(parent: str) -> str:
    return hashlib.sha256(parent.lower().encode("utf-8")).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200, help="Max dossiers to write this run")
    ap.add_argument("--min-siblings", type=int, default=1)
    args = ap.parse_args()

    if not DB.is_file():
        print(json.dumps({"ok": False, "error": "no registry"}))
        return 1

    entities = load_entities()
    con = sqlite3.connect(str(DB))
    rows = con.execute(
        "SELECT source_path, domain, dest_path FROM ingest WHERE source_path IS NOT NULL"
    ).fetchall()
    con.close()

    by_parent: dict[str, list[dict]] = defaultdict(list)
    for src, dom, dest in rows:
        if not src:
            continue
        p = Path(src)
        parent = str(p.parent)
        by_parent[parent].append(
            {"name": p.name, "domain": dom or "", "dest": dest or "", "source": src}
        )

    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    samples = []
    # prioritize medical/navy/va folders and larger sibling sets
    ranked = sorted(
        by_parent.items(),
        key=lambda kv: (
            0
            if re.search(r"medical|va\b|navy|nmcp|cnp|family", kv[0], re.I)
            else 1,
            -len(kv[1]),
        ),
    )

    for parent, files in ranked:
        if len(files) < args.min_siblings:
            continue
        if written >= args.limit:
            break
        names = [f["name"] for f in files]
        blob = parent + " " + " ".join(names[:80])
        dom_votes = Counter((f["domain"] or "unknown") for f in files)
        dossier = {
            "parent": parent,
            "parents": list(Path(parent).parts[-6:]),
            "file_count": len(files),
            "siblings_sample": names[:40],
            "domain_votes": dict(dom_votes.most_common(8)),
            "entity_hits": entity_hits(blob, entities),
            "date_hints": date_hints(blob),
            "summary": f"{Path(parent).name}: {len(files)} files; top domains {dom_votes.most_common(3)}",
            "updated_at": utc(),
            "method": "compound_folder_dossier_v1",
        }
        key = folder_key(parent)
        path = OUT / f"{key}.json"
        path.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
        # index by path
        written += 1
        if len(samples) < 12:
            samples.append(f"{Path(parent).name} n={len(files)} ent={dossier['entity_hits'][:3]}")

    # master index
    index = {
        "updated_at": utc(),
        "dossier_count_this_run": written,
        "total_parents_seen": len(by_parent),
        "out_dir": str(OUT),
    }
    (OUT / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"# Folder dossiers — {utc()}\n\n"
        f"Written **{written}** / parents seen **{len(by_parent)}**\n\n"
        + "\n".join(f"- {s}" for s in samples),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "written": written, "parents_seen": len(by_parent), "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
