#!/usr/bin/env python3
"""Evaluate compressed archives for training value.

Jeff 2026-07-13: Don't blanket-skip all zips. Distinguish:
  - VM/disk/media bulk (skip land)
  - Content archives (docs, mail, exports) → land or extract listing + harvest

Never prints file contents that look like secrets into stdout dumps.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Optional: rar/7z only if libs present later
OUT = Path(r"D:\HermesData\state\zip_eval_latest.json")
HARVEST_ROOT = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive\_zip_harvest"
)

SKIP_NAME = re.compile(
    r"(virtualbox|\.vdi|\.vmdk|vhdx|qcow|windows\s*1[01]|ubuntu\.iso|game|steam|gog|"
    r"backup\s*image|disk\s*image|music\s*lib|mp3)",
    re.I,
)
GOLD_NAME = re.compile(
    r"(medical|navy|nmcp|va\b|records|orders|eval|tax|legal|bcnr|nvlsp|"
    r"password|export|takeout|mail|outlook|pst|backup.?docs|dna|genome|"
    r"journal|notes|bloom|personal|scan)",
    re.I,
)
TEXTISH = re.compile(
    r"\.(txt|md|pdf|json|csv|docx?|xlsx?|html?|xml|log|ini|cfg|env|ya?ml)$", re.I
)
SECRETISH = re.compile(r"(password|secret|credential|\.pem|id_rsa|api[_-]?key)", re.I)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_archive(path: Path) -> dict:
    low = str(path).lower()
    name = path.name.lower()
    try:
        size = path.stat().st_size
    except OSError:
        return {"path": str(path), "decision": "skip", "reason": "unreadable"}

    # Hard skip: named like VM/disk/game
    if SKIP_NAME.search(name) or SKIP_NAME.search(low):
        return {
            "path": str(path),
            "size": size,
            "decision": "skip_bulk",
            "reason": "name_vm_disk_game_media",
        }

    # Huge anonymous zip still skip land of whole blob unless gold name
    if size > 500_000_000 and not GOLD_NAME.search(name):
        return {
            "path": str(path),
            "size": size,
            "decision": "skip_bulk",
            "reason": "huge_>500MB_no_gold_name",
        }

    # Prefer gold names always
    score = 0
    if GOLD_NAME.search(name) or GOLD_NAME.search(low):
        score += 50
    if size < 20_000_000:
        score += 20
    elif size < 100_000_000:
        score += 5
    else:
        score -= 10

    listing = []
    text_members = 0
    secret_members = 0
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for i, info in enumerate(zf.infolist()):
                    if i > 500:
                        break
                    n = info.filename
                    listing.append(n[:200])
                    if TEXTISH.search(n):
                        text_members += 1
                        score += 2
                    if SECRETISH.search(n):
                        secret_members += 1
                        score += 5  # valuable but quarantine later
        except Exception as e:
            return {
                "path": str(path),
                "size": size,
                "decision": "inspect_failed",
                "reason": str(e)[:120],
                "score": score,
            }
    else:
        # non-zip: name heuristics only
        if path.suffix.lower() in {".7z", ".rar"} and size > 100_000_000 and score < 50:
            return {
                "path": str(path),
                "size": size,
                "decision": "skip_bulk",
                "reason": "large_7z_rar_no_gold",
                "score": score,
            }

    if text_members >= 3 or score >= 45:
        decision = "land_or_harvest"
    elif text_members >= 1 or score >= 25:
        decision = "harvest_listing_and_small_text"
    else:
        decision = "skip_or_catalog"

    return {
        "path": str(path),
        "size": size,
        "decision": decision,
        "score": score,
        "text_members": text_members,
        "secret_members": secret_members,
        "listing_sample": listing[:40],
    }


def harvest_zip_text(path: Path, limit_files: int = 30) -> int:
    """Extract only small textish members into harvest folder."""
    if path.suffix.lower() != ".zip":
        return 0
    n = 0
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not TEXTISH.search(info.filename):
                    continue
                if info.file_size > 5_000_000:
                    continue
                if SECRETISH.search(info.filename):
                    # list only — do not extract secrets to training inbox
                    continue
                target = HARVEST_ROOT / path.stem / Path(info.filename).name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    continue
                with zf.open(info) as src, target.open("wb") as dst:
                    dst.write(src.read())
                meta = {
                    "source_zip": str(path),
                    "member": info.filename,
                    "harvested_at": utc(),
                }
                target.with_suffix(target.suffix + ".meta.json").write_text(
                    json.dumps(meta, indent=2), encoding="utf-8"
                )
                n += 1
                if n >= limit_files:
                    break
    except Exception:
        return n
    return n


def scan_roots(roots: list[Path], limit: int = 80) -> list[dict]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in {".zip", ".7z", ".rar"}:
                    continue
                found.append(p)
                if len(found) >= limit * 3:
                    break
        except OSError:
            continue
    # prefer smaller + gold names first
    def key(p: Path):
        try:
            sz = p.stat().st_size
        except OSError:
            sz = 1 << 60
        gold = 0 if GOLD_NAME.search(p.name) else 1
        return (gold, sz)

    found.sort(key=key)
    results = []
    for p in found[:limit]:
        results.append(classify_archive(p))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument(
        "--root",
        action="append",
        default=[],
        help="Root to scan (repeatable)",
    )
    args = ap.parse_args()
    roots = [Path(r) for r in args.root] or [
        Path(r"G:\Downloads"),
        Path(r"G:\MemoryCard_Backups"),
        Path(r"G:\SEC501_Restore"),
        Path(r"G:\Alex"),
        Path(r"D:\Documents"),
        Path(r"D:\Downloads"),
    ]
    results = scan_roots(roots, limit=args.limit)
    harvested = 0
    if args.harvest:
        for r in results:
            if r.get("decision") in {
                "land_or_harvest",
                "harvest_listing_and_small_text",
            }:
                harvested += harvest_zip_text(Path(r["path"]))
    summary = {
        "at": utc(),
        "scanned": len(results),
        "by_decision": {},
        "harvested_files": harvested,
        "results": results,
    }
    for r in results:
        d = r.get("decision") or "?"
        summary["by_decision"][d] = summary["by_decision"].get(d, 0) + 1
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "scanned": summary["scanned"],
                "by_decision": summary["by_decision"],
                "harvested_files": harvested,
                "out": str(OUT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
