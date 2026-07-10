#!/usr/bin/env python3
"""Duplicate / version / cross-format clustering for silo population.

Does NOT delete. Emits clusters + primary suggestion.
Exact hash, version stems (001/002/final), cross-format siblings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

POLICY = Path(r"D:\HermesData\config\dedup_policy.json")
DB = Path(r"D:\HermesData\state\lifecycle_index.sqlite3")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\dedup-clusters-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def sha256_file(path: Path, limit: int = 64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            if n >= limit:
                h.update(b"|TRUNC")
                break
    return h.hexdigest()


def normalize_stem(name: str, patterns: list[str]) -> str:
    stem = Path(name).stem
    s = stem
    for pat in patterns:
        s = re.sub(pat, "", s)
    s = re.sub(r"[_\-. ]+", " ", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def version_rank(name: str) -> tuple:
    """Higher is better primary candidate."""
    n = name.lower()
    score = 0
    if re.search(r"final|signed", n):
        score += 100
    if re.search(r"corrected|ocr", n):
        score += 50
    if re.search(r"rev(?:ision)?", n):
        score += 30
    m = re.search(r"(?:^|[_\-. ])v?(\d{1,4})(?:\.[a-z0-9]+)?$", Path(name).stem, re.I)
    if m:
        score += int(m.group(1))
    m2 = re.search(r"\((\d+)\)\.[a-z0-9]+$", n)
    if m2:
        score += int(m2.group(1))
    return (score, name)


def scan_dir(root: Path, limit: int = 5000) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            out.append(p)
            if len(out) >= limit:
                break
    return out


def cluster_files(files: list[Path], policy: dict) -> dict:
    patterns = policy["version_series"]["patterns"]
    by_hash: dict[str, list[Path]] = defaultdict(list)
    by_stem: dict[str, list[Path]] = defaultdict(list)
    by_stem_extgroup: dict[str, list[Path]] = defaultdict(list)

    ext_groups = policy["cross_format"]["groups"]

    def ext_group(ext: str) -> str:
        e = ext.lower()
        for i, g in enumerate(ext_groups):
            if e in g:
                return f"g{i}"
        return e

    meta = {}
    for p in files:
        try:
            digest = sha256_file(p)
            st = p.stat()
        except Exception as e:
            meta[str(p)] = {"error": str(e)}
            continue
        meta[str(p)] = {
            "sha256": digest,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "stem_norm": normalize_stem(p.name, patterns),
            "ext": p.suffix.lower(),
        }
        by_hash[digest].append(p)
        by_stem[meta[str(p)]["stem_norm"]].append(p)
        key = meta[str(p)]["stem_norm"] + "::" + ext_group(p.suffix)
        by_stem_extgroup[key].append(p)

    exact = []
    for digest, paths in by_hash.items():
        if len(paths) < 2:
            continue
        ranked = sorted(paths, key=lambda x: (-meta[str(x)]["mtime"], -meta[str(x)]["size"]))
        exact.append(
            {
                "type": "exact_hash",
                "sha256": digest,
                "primary": str(ranked[0]),
                "duplicates": [str(x) for x in ranked[1:]],
                "action": "keep_all_in_silo_link_dupes",
            }
        )

    versions = []
    for stem, paths in by_stem.items():
        if not stem or len(paths) < 2:
            continue
        # version series if names differ
        names = {p.name for p in paths}
        if len(names) < 2:
            continue
        ranked = sorted(paths, key=lambda x: version_rank(x.name), reverse=True)
        # only call version_series if looks versioned or multi-ext
        versiony = any(
            re.search(r"(?i)(\d{2,3}|final|ocr|corrected|v\d+)", p.stem) for p in paths
        )
        multi_ext = len({p.suffix.lower() for p in paths}) > 1
        if not versiony and not multi_ext:
            continue
        versions.append(
            {
                "type": "version_or_related_stem",
                "stem_norm": stem,
                "primary": str(ranked[0]),
                "members": [str(x) for x in ranked],
                "exts": sorted({p.suffix.lower() for p in paths}),
                "action": "keep_all_mark_primary_for_twin",
                "reason": "versiony" if versiony else "cross_format_stem",
            }
        )

    return {
        "ts": utc(),
        "file_count": len(files),
        "exact_duplicate_clusters": exact,
        "version_or_format_clusters": versions,
        "meta_sample": {k: meta[k] for k in list(meta)[:5]},
    }


def write_receipt(result: dict) -> None:
    lines = [
        f"# Dedup / version clusters — {result['ts']}",
        "",
        f"**Files scanned:** {result['file_count']}",
        f"**Exact hash clusters:** {len(result['exact_duplicate_clusters'])}",
        f"**Version/format clusters:** {len(result['version_or_format_clusters'])}",
        "",
        "## Policy",
        "- Silo population: **keep** related files; link relationships",
        "- Twin later: prefer **primary** per cluster",
        "- No deletes from this tool",
        "",
        "## Exact duplicates (sample)",
    ]
    for c in result["exact_duplicate_clusters"][:15]:
        lines.append(f"- primary `{Path(c['primary']).name}` · dupes={len(c['duplicates'])}")
    lines.append("")
    lines.append("## Version / cross-format (sample)")
    for c in result["version_or_format_clusters"][:20]:
        lines.append(
            f"- stem `{c['stem_norm'][:60]}` · primary `{Path(c['primary']).name}` · "
            f"n={len(c['members'])} exts={c['exts']} ({c['reason']})"
        )
    lines += [
        "",
        "[[Operations/Dedup-Versions-Overlap-CANONICAL-2026-07-10]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    json_path = Path(r"D:\HermesData\Backups\dedup-clusters-latest.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def maybe_update_lifecycle(result: dict) -> None:
    if not DB.exists():
        return
    try:
        con = sqlite3.connect(str(DB))
        cols = {r[1] for r in con.execute("PRAGMA table_info(files)").fetchall()}
        for col, decl in [
            ("dup_cluster", "TEXT"),
            ("dup_role", "TEXT"),
            ("dup_primary", "TEXT"),
        ]:
            if col not in cols:
                con.execute(f"ALTER TABLE files ADD COLUMN {col} {decl}")
        for c in result["exact_duplicate_clusters"]:
            cid = "exact:" + c["sha256"][:16]
            con.execute(
                "UPDATE files SET dup_cluster=?, dup_role=?, dup_primary=?, updated=? WHERE path=?",
                (cid, "primary", c["primary"], utc(), c["primary"]),
            )
            for d in c["duplicates"]:
                con.execute(
                    "UPDATE files SET dup_cluster=?, dup_role=?, dup_primary=?, updated=? WHERE path=?",
                    (cid, "duplicate", c["primary"], utc(), d),
                )
        for c in result["version_or_format_clusters"]:
            cid = "stem:" + c["stem_norm"][:80]
            con.execute(
                "UPDATE files SET dup_cluster=?, dup_role=?, dup_primary=?, updated=? WHERE path=?",
                (cid, "primary", c["primary"], utc(), c["primary"]),
            )
            for m in c["members"]:
                if m == c["primary"]:
                    continue
                con.execute(
                    "UPDATE files SET dup_cluster=?, dup_role=?, dup_primary=?, updated=? WHERE path=?",
                    (cid, "version_or_sibling", c["primary"], utc(), m),
                )
        con.commit()
        con.close()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args()
    policy = load_policy()
    files = scan_dir(Path(args.root), limit=args.limit)
    result = cluster_files(files, policy)
    write_receipt(result)
    maybe_update_lifecycle(result)
    print(
        json.dumps(
            {
                "files": result["file_count"],
                "exact_clusters": len(result["exact_duplicate_clusters"]),
                "version_clusters": len(result["version_or_format_clusters"]),
                "receipt": str(RECEIPT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
