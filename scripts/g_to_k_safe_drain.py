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
except Exception:
    def touch_classify(path, reg=None):
        return 2, "fallback"
    def score_path(path, rules=None, use_ai=False):
        return {"relevance": "train_ok", "score": 0, "class": 2}

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
K_SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
STAGING = K_SILO / "_Staging-From-G-Drive"
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-drain-receipt-latest.md")

# High-signal name heuristics → broad domain (open taxonomy)
RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"medical|dental|health|clinvar|genome|diagnosis|va\b|buddy statement", re.I), "Medical-Records"),
    (re.compile(r"navy|navadmin|eval|dd ?form|orders|service", re.I), "Navy-Service"),
    (re.compile(r"income|expense|tax|finance|cash|bank|receipt", re.I), "Core-Personal/Finance"),
    (re.compile(r"sermon|bible|gospel|spiritual|church|corinthians", re.I), "Core-Personal/Spiritual"),
    (re.compile(r"resume|career|job |interview|linkedin", re.I), "Core-Personal/Career"),
    (re.compile(r"family|letter from dad|wedding|kids", re.I), "Core-Personal/Family"),
    (re.compile(r"school|transcript|course|education|degree", re.I), "Core-Personal/Education"),
]


def domain_for(name: str) -> str:
    for pat, dom in RULES:
        if pat.search(name):
            return dom
    return "Core-Personal/_Inbox"


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


def iter_candidates(root: Path, limit: int) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        # skip huge archives in pilot
        if p.suffix.lower() in {".7z", ".zip", ".iso", ".vmdk"} and p.stat().st_size > 50_000_000:
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

    planned = []
    for src_root in sources:
        for f in iter_candidates(src_root, args.limit // max(1, len(sources)) + 5):
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
    for src, dest, dom, root in planned:
        status = "planned"
        if dest.exists():
            status = "skip-exists"
            skipped += 1
        elif args.apply:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                digest = sha256_file(src)
                meta = {
                    "source": str(src),
                    "source_root": root,
                    "dest": str(dest),
                    "domain": dom,
                    "sha256": digest,
                    "copied_at": TS,
                    "policy": "copy-only-no-purge",
                }
                dest.with_suffix(dest.suffix + ".meta.json").write_text(
                    json.dumps(meta, indent=2), encoding="utf-8"
                )
                meta_batch.append(meta)
                status = "copied"
                copied += 1
            except Exception as e:
                status = f"ERR {e}"
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
