#!/usr/bin/env python3
"""Safe G→K drain: COPY ONLY with provenance. Default = dry-run.

Sources: MemoryCard Google Drive (+archive) only — NOT live D: My Drive.
Dest: K:\\Phronesis-Sovereign\\Personal-Digital-Silo (broad domains).

NEVER deletes source. NEVER purges Drive.
Jeff green-light required for --apply and for any future purge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

# touch policy
import sys
sys.path.insert(0, str(Path(r"D:/HermesData/scripts")))
try:
    from touch_policy import classify as touch_classify
    from relevance_score import score_path
    from ingest_registry import (
        connect as ingest_connect,
        already_ingested_source,
        already_have_hash,
        register as ingest_register,
        sha256_file as ingest_sha,
    )
except Exception:
    def touch_classify(path, reg=None):
        return 2, "fallback"
    def score_path(path, rules=None, use_ai=False):
        return {"relevance": "train_ok", "score": 0, "class": 2}
    ingest_connect = None
    already_ingested_source = None
    already_have_hash = None
    ingest_register = None

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
K_SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
STAGING = K_SILO / "_Staging-From-G-Drive"
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-drain-receipt-latest.md")

# Domain routing SSOT (expanded after MemoryCard trial lessons)
try:
    from domain_route import domain_for as _domain_for
except Exception:
    def _domain_for(name: str, path_hint: str = "") -> str:
        return "Core-Personal/_Inbox"


def domain_for(name: str, path_hint: str = "") -> str:
    """Strip routing noise; preserve real filename on disk separately."""
    return _domain_for((name or "").strip(), path_hint)


def copy_file(src: Path, dest: Path) -> str:
    """Efficient copy: robocopy for large files, shutil.copy2 otherwise.

    Returns method tag: robocopy|shutil
    """
    import subprocess
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    # robocopy shines on larger files / Windows paths
    if size >= 8 * 1024 * 1024:  # 8 MB+
        # robocopy needs dir args; copy single file
        cmd = [
            "robocopy",
            str(src.parent),
            str(dest.parent),
            src.name,
            "/J",  # unbuffered
            "/R:2",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NC",
            "/NS",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        # robocopy exit 0-7 success
        if r.returncode < 8 and dest.exists():
            return "robocopy"
        # fallback
    shutil.copy2(src, dest)
    return "shutil"


def sha256_file(path: Path, limit: int = 32 * 1024 * 1024) -> str:
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
                h.update(b"|TRUNCATED_HASH")
                break
    return h.hexdigest()


def iter_candidates(
    root: Path,
    limit: int,
    skip_sources: set[str] | None = None,
    skip_hashes: set[str] | None = None,
) -> list[Path]:
    """Yield up to `limit` *new* candidates (skips known sources).

    Avoids alpha-prefix thrash where every wave re-plans the same first N files.
    """
    out: list[Path] = []
    if not root.exists():
        return out
    skip_sources = skip_sources or set()
    scanned = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name.endswith(".meta.json"):
            continue
        scanned += 1
        try:
            if p.suffix.lower() in {".7z", ".zip", ".iso", ".vmdk"} and p.stat().st_size > 50_000_000:
                continue
        except Exception:
            continue
        sp = str(p)
        if sp in skip_sources:
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually copy (default dry-run)")
    ap.add_argument("--limit", type=int, default=40, help="Max files this wave")
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source root (repeatable). Defaults to MemoryCard GD + live My Drive",
    )
    args = ap.parse_args()
    # Default: historical MemoryCard GD only (NOT live D: My Drive — avoid re-dupe)
    sources = [Path(s) for s in args.source] or [
        Path(r"G:\MemoryCard_Backups\Google Drive"),
        Path(r"G:\MemoryCard_Backups\Google Drive(archive)"),
    ]

    # Known sources from ingest registry → skip early (wave efficiency)
    skip_sources: set[str] = set()
    icon_pre = ingest_connect() if ingest_connect else None
    if icon_pre is not None:
        try:
            rows = icon_pre.execute(
                "SELECT source_path FROM ingest WHERE status IN ('copied','verified','processed')"
            ).fetchall()
            skip_sources = {r[0] if not hasattr(r, 'keys') else r['source_path'] for r in rows}
        except Exception:
            pass

    planned = []
    per = max(args.limit // max(1, len(sources)) + 5, args.limit)
    for src_root in sources:
        for f in iter_candidates(src_root, per, skip_sources=skip_sources):
            dom = domain_for(f.name)
            rel = f.relative_to(src_root) if f.is_relative_to(src_root) else Path(f.name)
            dest = K_SILO / dom / "from-g-drive" / rel
            planned.append((f, dest, dom, str(src_root)))
            if len(planned) >= args.limit:
                break
        if len(planned) >= args.limit:
            break

    # Enforce Class 2 only (personal purge-eligible). Skip class 1/3.
    filtered = []
    for src, dest, dom, root in planned:
        cls, note = touch_classify(src)
        if cls != 2:
            continue
        rel = score_path(src)
        if rel.get("relevance") == "noise":
            continue
        if rel.get("relevance") == "train_weak" and dom.endswith("_Inbox"):
            pass  # still allow weak into inbox
        filtered.append((src, dest, dom, root))
    planned = filtered

    copied = skipped = 0
    lines = [
        f"# G→K safe drain receipt — {TS}",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}",
        f"**Limit:** {args.limit}",
        "",
        "| Source file | Domain | Dest | Status |",
        "|-------------|--------|------|--------|",
    ]
    meta_batch = []
    icon = ingest_connect() if ingest_connect else None
    for src, dest, dom, root in planned:
        status = "planned"
        # Registry / filesystem guards against re-processing
        if dest.exists():
            status = "skip-exists"
            skipped += 1
        elif icon is not None and already_ingested_source and already_ingested_source(icon, str(src)):
            status = "skip-registry-source"
            skipped += 1
        elif args.apply:
            try:
                digest = sha256_file(src)
                if icon is not None and already_have_hash and already_have_hash(icon, digest):
                    status = "skip-registry-hash"
                    skipped += 1
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    method = copy_file(src, dest)
                    meta = {
                        "source": str(src),
                        "source_root": root,
                        "dest": str(dest),
                        "domain": dom,
                        "sha256": digest,
                        "size": src.stat().st_size,
                        "copied_at": TS,
                        "policy": "copy-only-no-purge",
                        "copy_method": method,
                    }
                    dest.with_suffix(dest.suffix + ".meta.json").write_text(
                        json.dumps(meta, indent=2), encoding="utf-8"
                    )
                    meta_batch.append(meta)
                    if ingest_register:
                        ingest_register(
                            icon, str(src), str(dest), digest=digest,
                            size=src.stat().st_size, domain=dom, status="copied",
                        )
                        icon.commit()
                    status = "copied"
                    copied += 1
            except Exception as e:
                status = f"ERR {e}"
        elif not args.apply and icon is not None and already_ingested_source and already_ingested_source(icon, str(src)):
            status = "would-skip-registry"
            skipped += 1
        lines.append(f"| `{src.name[:60]}` | {dom} | `{dest}` | {status} |")

    if args.apply and meta_batch:
        STAGING.mkdir(parents=True, exist_ok=True)
        (STAGING / f"batch-{TS}.json").write_text(json.dumps(meta_batch, indent=2), encoding="utf-8")

    lines += [
        "",
        f"**Copied:** {copied} · **Skipped:** {skipped} · **Planned rows:** {len(planned)}",
        "",
        "## Guardrails",
        "- Copy only — sources untouched",
        "- No Drive purge in this script",
        "- Broad domains only (open taxonomy)",
        "- Full drain needs many waves + Jeff green light before any purge",
        "",
        "[[Operations/G-to-K-Drain-Assurance-2026-07-10]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "planned": len(planned), "copied": copied, "receipt": str(RECEIPT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
