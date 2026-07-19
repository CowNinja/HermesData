#!/usr/bin/env python3
"""Batch P1 training derivatives under a domain folder (idempotent).

Hang-fix 2026-07-14:
- Fail-soft on per-file TimeoutExpired.
- Skip thin imaging / plot junk.
- Prefer gold path keywords.
- max-scan cap + OCR-queue-first discovery (avoid multi-minute Medical rglob hangs).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

try:
    from silo_relevance_heuristics import train_meta_flags as _train_meta_flags
except Exception:
    _train_meta_flags = None

SCRIPT = Path(r"D:\HermesData\scripts\training_derivative_text.py")
OCR_DB = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")

SKIP_NAME_RE = re.compile(
    r"(anomaly|aGradient|scymed|target.?body|BMI.?plot|nutrition.?plot|"
    r"formula|equation crop|pagebackground|pagefooter|pagetop|"
    r"address\.png|phone\.png)",
    re.I,
)
SKIP_PATH_RE = re.compile(
    r"(HealthMatters\.io|\\images\\|/images/|thin.?imaging)",
    re.I,
)
GOLD_HINT = re.compile(
    r"(VAMC|NMCP|DD280|NAVPERS|PHA|AHLTA|TRICARE|MyHealtheVet|"
    r"SF600|clinical|Navy|Elrod|Enterprise|SARP|disability)",
    re.I,
)


def should_skip(p: Path) -> bool:
    name = p.name
    s = str(p)
    if SKIP_NAME_RE.search(name) or SKIP_PATH_RE.search(s):
        return True
    low = name.lower()
    if low.endswith((".jpg.ocr.md", ".jpeg.ocr.md", ".png.ocr.md", ".tif.ocr.md", ".tiff.ocr.md")):
        if not GOLD_HINT.search(s):
            return True
    return False


def mark_skip(src: Path, reason: str) -> None:
    train = Path(str(src) + ".train.md")
    if train.is_file():
        return
    try:
        train.write_text(
            f"---\nsource: {src}\nskipped: true\nreason: {reason}\n---\n\n[skipped]\n",
            encoding="utf-8",
            errors="replace",
        )
        Path(str(src) + ".train.meta.json").write_text(
            json.dumps({"source": str(src), "skipped": True, "reason": reason}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def candidates_from_ocr_queue(limit: int, root: Path) -> list[Path]:
    """Prefer ok_text sources that still lack .train.md — O(queue) not O(tree)."""
    out: list[Path] = []
    if not OCR_DB.is_file():
        return out
    root_s = str(root).lower().replace("/", "\\")
    try:
        con = sqlite3.connect(str(OCR_DB), timeout=30)
        rows = con.execute(
            "SELECT path FROM ocr_queue WHERE status='ok_text' ORDER BY chars DESC LIMIT ?",
            (max(limit * 8, 200),),
        ).fetchall()
        con.close()
    except Exception:
        return out
    for (path,) in rows:
        if not path:
            continue
        p = Path(path)
        if root_s not in str(p).lower().replace("/", "\\"):
            # allow ocr.md sidecar as source when path is binary but ocr.md exists
            pass
        if not p.is_file():
            # try .ocr.md sibling as text source
            ocr_md = Path(str(p) + ".ocr.md")
            if ocr_md.is_file():
                p = ocr_md
            else:
                continue
        if Path(str(p) + ".train.md").exists():
            continue
        if should_skip(p):
            mark_skip(p, "junk_or_thin_imaging")
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def candidates_from_walk(root: Path, limit: int, max_scan: int) -> list[Path]:
    # 2026-07-18: include takeout/html/email — Google_Backups land wave is mostly .html
    exts = {".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm", ".eml", ".msg", ".rtf"}
    gold: list[Path] = []
    other: list[Path] = []
    # scanned = eligibility candidates (not raw rglob nodes).
    # 2026-07-19: Medical-Records prefix is train-saturated; counting every
    # node toward max_scan left attempted=0 while deep unprocessed PDFs remain.
    scanned = 0
    nodes = 0
    node_cap = max(max_scan * 40, 50000)
    for pth in root.rglob("*"):
        nodes += 1
        if nodes > node_cap:
            break
        if not pth.is_file():
            continue
        if pth.suffix.lower() not in exts:
            continue
        if pth.name.endswith(".meta.json") or ".train." in pth.name:
            continue
        if pth.name.endswith(".train.md"):
            continue
        if Path(str(pth) + ".train.md").exists():
            continue
        scanned += 1
        if scanned > max_scan:
            break
        if should_skip(pth):
            mark_skip(pth, "junk_or_thin_imaging")
            continue
        (gold if GOLD_HINT.search(str(pth)) else other).append(pth)
        if len(gold) + len(other) >= max(limit * 4, 80):
            break
    return (gold + other)[:limit]


def candidates_from_registry(root: Path, limit: int) -> list[Path]:
    """Prefer recent unprocessed lands under root (O(registry) not full-tree).

    Overnight 2026-07-18 lesson: Google_Backups HTML never hit OCR queue and
    walk defaulted to Medical-only PDF/txt — train stayed at attempted=0.
    """
    out: list[Path] = []
    reg = Path(r"D:/HermesData/state/ingest_registry.sqlite3")
    if not reg.is_file():
        return out
    root_n = str(root).replace("/", "\\").rstrip("\\")
    try:
        con = sqlite3.connect(str(reg), timeout=30)
        con.execute("PRAGMA busy_timeout=30000")
        rows = con.execute(
            """
            SELECT dest_path FROM ingest
            WHERE dest_path LIKE ?
              AND (process_status IS NULL OR process_status IN
                   ('unprocessed','extracted','context_enriched','ocr_queued'))
            ORDER BY COALESCE(first_seen, last_seen) DESC
            LIMIT ?
            """,
            (root_n + "%", max(limit * 12, 120)),
        ).fetchall()
        con.close()
    except Exception:
        return out
    exts = {".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm", ".eml", ".msg", ".rtf"}
    for (dest,) in rows:
        if not dest:
            continue
        pth = Path(dest)
        if not pth.is_file():
            continue
        if pth.suffix.lower() not in exts and not Path(str(pth) + ".ocr.md").is_file():
            # allow binary+ocr sidecar
            ocr_md = Path(str(pth) + ".ocr.md")
            if ocr_md.is_file():
                pth = ocr_md
            else:
                continue
        if Path(str(pth) + ".train.md").exists():
            continue
        if should_skip(pth):
            mark_skip(pth, "junk_or_thin_imaging")
            continue
        out.append(pth)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default=r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Medical-Records",
    )
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--max-scan", type=int, default=4000, help="rglob file cap fallback")
    ap.add_argument(
        "--walk-only",
        action="store_true",
        help="skip OCR-queue discovery",
    )
    args = ap.parse_args()
    root = Path(args.root)
    files: list[Path] = []
    source = "none"
    # 1) registry-recent (fast, covers new HTML land waves)
    reg_files = candidates_from_registry(root, args.limit)
    if reg_files:
        files.extend(reg_files)
        source = "registry"
    # 2) OCR queue gold
    if not args.walk_only and len(files) < args.limit:
        ocr_files = candidates_from_ocr_queue(args.limit - len(files), root)
        seen = {str(f) for f in files}
        for w in ocr_files:
            if str(w) not in seen:
                files.append(w)
                seen.add(str(w))
        if ocr_files:
            source = f"{source}+ocr_queue" if source != "none" else "ocr_queue"
    # 3) walk fallback
    if len(files) < args.limit:
        need = args.limit - len(files)
        walked = candidates_from_walk(root, need, args.max_scan)
        seen = {str(f) for f in files}
        for w in walked:
            if str(w) not in seen:
                files.append(w)
                seen.add(str(w))
        if walked:
            source = f"{source}+walk" if source != "none" else "walk"
    if source == "none":
        source = "empty"
    files = files[: args.limit]
    ok = 0
    skipped = 0
    timed_out = 0
    try:
        from ingest_registry import connect as reg_connect

        icon = reg_connect()
    except Exception:
        icon = None
    for f in files:
        try:
            r = subprocess.run(
                [sys.executable, str(SCRIPT), str(f)],
                capture_output=True,
                text=True,
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            timed_out += 1
            mark_skip(f, f"timeout_{args.timeout}s")
            continue
        except Exception as e:
            mark_skip(f, f"error:{type(e).__name__}")
            continue
        if r.returncode == 0:
            ok += 1
            if icon is not None:
                try:
                    icon.execute(
                        "UPDATE ingest SET process_status='derivative_ok' WHERE dest_path=? OR dest_path LIKE ?",
                        (str(f), str(f).replace("\\", "/")),
                    )
                except Exception:
                    pass
        else:
            skipped += 1
    if icon is not None:
        try:
            icon.commit()
        except Exception:
            pass
    print(
        json.dumps(
            {
                "root": str(root),
                "source": source,
                "attempted": len(files),
                "ok": ok,
                "skipped": skipped,
                "timed_out": timed_out,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
