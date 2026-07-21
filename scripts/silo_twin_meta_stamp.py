#!/usr/bin/env python3
"""Stamp twin metadata onto existing .train.md / .train.meta.json (post-OCR era).

Bounded, idempotent. Adds temporal + domain tags + gold tier for retrieval.
No re-OCR. $0 Grok.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"D:/HermesData/scripts")
from silo_relevance_heuristics import (  # type: ignore
    gold_tier,
    temporal_relevance,
    train_meta_flags,
)

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-twin-meta-stamp-latest.md")
LIGHT = Path(r"D:\HermesData\state\k_light_index.jsonl")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_tags(path: Path) -> list[str]:
    s = str(path).lower().replace("\\", "/")
    tags = []
    if "medical" in s or "vamc" in s or "nmcp" in s:
        tags.append("medical")
    if "navy" in s or "ncdoc" in s or "navpers" in s or "elrod" in s:
        tags.append("navy")
    if "family" in s or "booksbloom" in s:
        tags.append("family")
    if "booksbloom" in s or "projects/from-g-drive/booksbloom" in s:
        tags.append("business")
    if "finance" in s:
        tags.append("finance")
    if not tags:
        tags.append("personal")
    return tags


def process_train_md(train: Path) -> dict | None:
    # source path is train without .train.md
    if str(train).endswith(".train.md"):
        src = Path(str(train)[:-9])  # strip .train.md
    else:
        src = train
    meta_path = Path(str(src) + ".train.meta.json")
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            meta = {}
    # 2026-07-19: skip only when full stamp incl. twin_scopes is present.
    # Earlier waves wrote temporal+tags but omitted twin_scopes from train_meta_flags.
    if (
        meta.get("temporal")
        and meta.get("tags")
        and meta.get("stamped_at")
        and meta.get("twin_scopes")
        and meta.get("primary_scope")
    ):
        return None
    flags = train_meta_flags(src)
    tags = domain_tags(src)
    tier = gold_tier(src)
    scopes = flags.get("twin_scopes") or []
    meta.update(
        {
            "source": str(src),
            "stamped_at": utc(),
            "temporal": flags.get("temporal"),
            "use_as_current_fact": flags.get("use_as_current_fact"),
            "use_as_historical_graph": flags.get("use_as_historical_graph"),
            "twin_training_value": flags.get("twin_training_value"),
            "twin_scopes": scopes,
            "primary_scope": flags.get("primary_scope")
            or (scopes[0] if scopes else "life_archive"),
            "gold_tier": tier,
            "tags": tags,
            "family_business": "family" in tags or "business" in tags,
            "note": flags.get("note") or "",
        }
    )
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # ensure train.md has YAML-ish temporal line once
    try:
        body = train.read_text(encoding="utf-8", errors="replace")
        if "temporal:" not in body[:500] and "twin_meta temporal=" not in body[:500]:
            header = (
                f"<!-- twin_meta temporal={meta['temporal']} tags={','.join(tags)} "
                f"scopes={','.join(scopes)} gold={tier} -->\n"
            )
            train.write_text(header + body, encoding="utf-8", errors="replace")
        elif "scopes=" not in body[:500] and "twin_meta" in body[:500]:
            # light backfill note on existing header line
            pass
    except Exception:
        pass
    return meta


def _already_fully_stamped(train: Path) -> bool:
    """Fast pre-check so already-stamped heads don't burn the scan budget."""
    if str(train).endswith(".train.md"):
        src = Path(str(train)[:-9])
    else:
        src = train
    meta_path = Path(str(src) + ".train.meta.json")
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False
    return bool(
        meta.get("temporal")
        and meta.get("tags")
        and meta.get("stamped_at")
        and meta.get("twin_scopes")
        and meta.get("primary_scope")
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default=str(SILO / "Medical-Records"),
    )
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--also-navy", action="store_true")
    ap.add_argument("--also-family", action="store_true")
    ap.add_argument("--also-booksbloom", action="store_true")
    ap.add_argument(
        "--max-scan",
        type=int,
        default=2500,
        help="stop walking after N *candidate* train.md files (already-stamped fast-skips are separate)",
    )
    ap.add_argument(
        "--skip-offset",
        type=int,
        default=0,
        help="skip first N train.md encounters (cursor resume past already-stamped head)",
    )
    ap.add_argument(
        "--max-already-skip",
        type=int,
        default=20000,
        help="max already-stamped fast-skips before giving up on this root (cursor burn protection)",
    )
    args = ap.parse_args()
    roots = [Path(args.root)]
    if args.also_navy:
        roots.append(SILO / "Navy-Service")
    if args.also_family:
        roots.append(SILO / "Core-Personal" / "Family")
    if args.also_booksbloom:
        roots.append(
            SILO / "Core-Personal" / "Projects" / "from-g-drive" / "Booksbloom"
        )
    stamped = 0
    skipped = 0
    scanned = 0
    offset_skipped = 0
    already_fast = 0
    light_rows = []
    skip_left = max(0, int(args.skip_offset or 0))
    walked = 0  # every train.md seen (for cursor advance)
    for root in roots:
        if not root.is_dir():
            continue
        for train in root.rglob("*.train.md"):
            if stamped >= args.limit:
                break
            if train.name.endswith(".train.meta.json"):
                continue
            walked += 1
            if skip_left > 0:
                skip_left -= 1
                offset_skipped += 1
                continue
            # Prefer unstamped: fast-skip full stamps without counting toward max_scan
            if _already_fully_stamped(train):
                skipped += 1
                already_fast += 1
                if already_fast >= int(args.max_already_skip or 20000):
                    break
                continue
            if scanned >= args.max_scan:
                break
            scanned += 1
            meta = process_train_md(train)
            if meta is None:
                skipped += 1
                continue
            stamped += 1
            light_rows.append(
                {
                    "path": meta.get("source"),
                    "temporal": meta.get("temporal"),
                    "tags": meta.get("tags"),
                    "gold_tier": meta.get("gold_tier"),
                    "twin_scopes": meta.get("twin_scopes") or [],
                    "primary_scope": meta.get("primary_scope"),
                    "train": str(train),
                }
            )
        if stamped >= args.limit or scanned >= args.max_scan or already_fast >= int(args.max_already_skip or 20000):
            break
    # append light index then compact unique paths
    LIGHT.parent.mkdir(parents=True, exist_ok=True)
    with LIGHT.open("a", encoding="utf-8") as f:
        for row in light_rows:
            f.write(json.dumps(row) + "\n")
    # compact: keep last-seen meta per path
    try:
        seen: dict[str, dict] = {}
        if LIGHT.is_file():
            for line in LIGHT.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                key = o.get("path") or o.get("train")
                if key:
                    seen[key] = o
            LIGHT.write_text(
                "\n".join(json.dumps(v) for v in seen.values()) + ("\n" if seen else ""),
                encoding="utf-8",
            )
            light_n = len(seen)
        else:
            light_n = 0
    except Exception:
        light_n = -1
    payload = {
        "at": utc(),
        "root": str(args.root),
        "skip_offset_in": int(args.skip_offset or 0),
        "stamped": stamped,
        "skipped_already": skipped,
        "scanned": scanned,
        "offset_skipped": offset_skipped,
        "already_fast_skipped": already_fast,
        "walked": walked,
        # next cursor resume position within this root walk order
        "next_skip_offset": int(args.skip_offset or 0) + offset_skipped + already_fast + scanned,
        "k_light_unique": light_n,
        "light_index": str(LIGHT),
        "receipt": str(RECEIPT),
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        f"# Twin meta stamp — {payload['at']}\n\n"
        f"Stamped **{stamped}** · skipped already **{skipped}** · scanned {scanned} · "
        f"offset_skipped {offset_skipped} · already_fast {already_fast} · walked {walked} · "
        f"k_light unique **{light_n}** · `{LIGHT}`\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```\n",
        encoding="utf-8",
    )
    # machine receipt for board (survives md parse flakes)
    try:
        Path(r"D:/HermesData/state/silo_twin_meta_stamp_latest.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
