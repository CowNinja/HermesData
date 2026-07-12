#!/usr/bin/env python3
"""Multi-provenance context: same hash/file in different folders → merge neighborhood.

Jeff 2026-07-12: when scan finds existing content, don't waste the hit —
ingest additional path/sibling context so classification & twin get richer
evidence from every home the file lived in.

Writes/updates:
  - dest .meta.json  → provenances[] list
  - dest .context.json → merged parents/siblings samples
  - registry notes optional
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def neighborhood(path: Path, limit: int = 24) -> dict:
    parent = path.parent
    sibs = []
    try:
        for p in parent.iterdir():
            if p.name.startswith("."):
                continue
            sibs.append(p.name)
            if len(sibs) >= limit:
                break
    except OSError:
        pass
    parts = list(path.parts)
    return {
        "path": str(path),
        "parent": str(parent),
        "parents": parts[-6:] if len(parts) > 6 else parts,
        "siblings_sample": sorted(sibs)[:limit],
        "seen_at": utc(),
    }


def merge_meta(dest: Path, source: Path, digest: str = "", domain: str = "") -> dict:
    meta_path = Path(str(dest) + ".meta.json")
    if not meta_path.is_file():
        # also try dest.with_suffix style used by drain
        alt = dest.with_suffix(dest.suffix + ".meta.json")
        meta_path = alt if alt.is_file() else meta_path

    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    prov = meta.get("provenances") or []
    # seed primary if empty
    if meta.get("source") and not any(p.get("path") == meta.get("source") for p in prov):
        try:
            prov.append(neighborhood(Path(meta["source"])))
        except Exception:
            prov.append({"path": meta.get("source"), "seen_at": utc()})

    nb = neighborhood(source)
    if digest:
        nb["sha256"] = digest
    if domain:
        nb["domain_hint"] = domain

    # de-dupe by path
    paths = {p.get("path") for p in prov}
    if nb["path"] not in paths:
        prov.append(nb)

    meta["provenances"] = prov
    meta["provenance_count"] = len(prov)
    meta["last_provenance_at"] = utc()
    if digest and not meta.get("sha256"):
        meta["sha256"] = digest

    # merge context sidecar
    ctx_path = Path(str(dest) + ".context.json")
    if not ctx_path.is_file():
        ctx_path = dest.with_suffix(dest.suffix + ".context.json")
    ctx = {}
    if ctx_path.is_file():
        try:
            ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        except Exception:
            ctx = {}
    homes = ctx.get("homes") or []
    if nb["path"] not in {h.get("path") for h in homes}:
        homes.append(nb)
    ctx["homes"] = homes[:20]
    ctx["updated"] = utc()
    ctx["method"] = "multi_provenance_merge"
    # flat sibling union for classify
    sib_union = []
    seen = set()
    for h in homes:
        for s in h.get("siblings_sample") or []:
            if s not in seen:
                seen.add(s)
                sib_union.append(s)
    ctx["siblings_union"] = sib_union[:40]
    parent_union = []
    pseen = set()
    for h in homes:
        for p in h.get("parents") or []:
            if p not in pseen:
                pseen.add(p)
                parent_union.append(p)
    ctx["parents_union"] = parent_union[-20:]

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    ctx_path.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
    return {"meta": str(meta_path), "context": str(ctx_path), "homes": len(homes)}


def process_registry_dupes(limit: int = 50) -> dict:
    """Find hashes with multiple source_paths; merge context onto dest."""
    if not REG.is_file():
        return {"error": "no registry"}
    con = sqlite3.connect(str(REG))
    rows = con.execute(
        """
        SELECT sha256, COUNT(*) c FROM ingest
        WHERE sha256 IS NOT NULL AND sha256 != ''
        GROUP BY sha256 HAVING c > 1
        ORDER BY c DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    done = 0
    for sha, c in rows:
        paths = con.execute(
            "SELECT source_path, dest_path, domain FROM ingest WHERE sha256=? LIMIT 12",
            (sha,),
        ).fetchall()
        dest = None
        for sp, dp, dom in paths:
            if dp and Path(dp).is_file():
                dest = Path(dp)
                break
        if not dest:
            continue
        for sp, dp, dom in paths:
            if not sp:
                continue
            src = Path(sp)
            if not src.is_file():
                # still record path neighborhood from path string
                try:
                    merge_meta(dest, src, digest=sha, domain=dom or "")
                    done += 1
                except Exception:
                    pass
            else:
                try:
                    merge_meta(dest, src, digest=sha, domain=dom or "")
                    done += 1
                except Exception:
                    pass
    con.close()
    return {"multi_hash_groups": len(rows), "merges": done}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--source", type=str, default="")
    ap.add_argument("--dest", type=str, default="")
    args = ap.parse_args()
    if args.source and args.dest:
        r = merge_meta(Path(args.dest), Path(args.source))
        print(json.dumps(r, indent=2))
        return 0
    r = process_registry_dupes(limit=args.limit)
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
