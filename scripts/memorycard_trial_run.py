#!/usr/bin/env python3
"""MemoryCard Google Drive bounded ingestion trial.

Scripts + registry only. No cloud LLM calls.
Default: apply 500 files from both historical GD trees.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\memorycard-trial-run-latest.md")
sys.path.insert(0, str(SCRIPTS))


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(args: list[str], timeout: int = 900) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, *[str(a) for a in args]],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SCRIPTS),
    )
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))


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


def verify_recent_meta(limit: int = 80) -> dict:
    """Verify dest exists + hash matches meta for recent from-g-drive metas."""
    root = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
    metas = sorted(
        root.rglob("from-g-drive/**/*.meta.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    ok = bad = missing = 0
    details = []
    for m in metas:
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except Exception as e:
            bad += 1
            details.append(f"meta-read {m.name}: {e}")
            continue
        dest = Path(data.get("dest") or str(m).replace(".meta.json", ""))
        src = Path(data.get("source") or "")
        expect = data.get("sha256") or ""
        if not dest.is_file():
            missing += 1
            continue
        try:
            got = sha256_file(dest)
        except Exception as e:
            bad += 1
            details.append(f"hash dest {dest.name}: {e}")
            continue
        if expect and got != expect:
            # re-hash source if present
            if src.is_file():
                sgot = sha256_file(src)
                if sgot == got:
                    ok += 1  # meta stale but dest==src
                    continue
            bad += 1
            details.append(f"hash mismatch {dest.name}")
        else:
            ok += 1
    return {
        "checked": len(metas),
        "ok": ok,
        "bad": bad,
        "missing_dest": missing,
        "details": details[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    lines = [
        f"# MemoryCard ingestion trial — {utc()}",
        "",
        f"**Limit:** {args.limit} · **Mode:** {'DRY-RUN' if args.dry_run else 'APPLY'}",
        f"**Intelligence:** scripts + rules only (no Grok/cloud LLM in this runner)",
        "",
    ]
    # preflight
    if not args.skip_preflight:
        code, out = run([SCRIPTS / "memorycard_trial_preflight.py"], 500)
        lines.append(f"## Preflight exit={code}")
        lines.append("```")
        lines.append(out[-1200:])
        lines.append("```")
        if code != 0:
            lines.append("**ABORT:** preflight failed")
            RECEIPT.write_text("\n".join(lines), encoding="utf-8")
            print(json.dumps({"aborted": True, "reason": "preflight"}))
            return 2

    # drain
    drain_args = [SCRIPTS / "g_to_k_safe_drain.py", "--limit", str(args.limit)]
    if not args.dry_run:
        drain_args.append("--apply")
    # explicit sources
    drain_args += [
        "--source",
        r"G:\MemoryCard_Backups\Google Drive",
        "--source",
        r"G:\MemoryCard_Backups\Google Drive(archive)",
    ]
    code, out = run(drain_args, 1200)
    lines.append(f"## Drain exit={code}")
    lines.append("```")
    lines.append(out[-1500:])
    lines.append("```")

    # registry stats
    code2, out2 = run([SCRIPTS / "ingest_registry.py", "stats"], 60)
    lines.append(f"## Registry exit={code2}")
    lines.append("```")
    lines.append(out2[-800:])
    lines.append("```")

    # verify
    v = verify_recent_meta(100)
    lines.append("## Verify recent metas")
    lines.append("```")
    lines.append(json.dumps(v, indent=2))
    lines.append("```")

    # dedup light on silo
    code3, out3 = run(
        [
            SCRIPTS / "dedup_cluster.py",
            "--root",
            r"K:\Phronesis-Sovereign\Personal-Digital-Silo",
            "--limit",
            "2500",
        ],
        600,
    )
    lines.append(f"## Dedup exit={code3}")
    lines.append("```")
    lines.append(out3[-600:])
    lines.append("```")

    elapsed = time.time() - t0
    success = code == 0 and v.get("bad", 0) == 0
    lines += [
        "",
        f"**Elapsed:** {elapsed:.1f}s",
        f"**Trial result:** {'PASS' if success else 'REVIEW'}",
        "",
        "[[Operations/G-MemoryCard-Ingestion-Trial-Five-Actions-2026-07-10]]",
        "[[Operations/logs/memorycard-trial-preflight-latest]]",
        "",
    ]
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "success": success,
        "drain_exit": code,
        "verify": v,
        "elapsed_s": round(elapsed, 1),
        "receipt": str(RECEIPT),
        "limit": args.limit,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
