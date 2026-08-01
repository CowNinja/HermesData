#!/usr/bin/env python3
"""Push a *clean orphan* PhronesisVault tip to GitHub without force-pushing master.

Method (v2): git archive of live HEAD -> fresh repo (1 commit) -> push branch
github-cns-mirror. Avoids shallow-clone missing-object rejections and avoids
shipping 100MB+ historical sqlite blobs.

Safe defaults:
  - Does NOT force-push master/main
  - Does NOT rewrite the live vault repo
  - Strips sqlite, secrets, and bulky Operations/logs dumps

Usage:
  python D:/HermesData/scripts/vault_github_clean_mirror_push.py
  python D:/HermesData/scripts/vault_github_clean_mirror_push.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
STATE = HERMES / "state" / "vault_github_clean_mirror_last.json"
TMP_ROOT = HERMES / "tmp" / "vault-gh-orphan-mirror"
DEFAULT_BRANCH = "github-cns-mirror"
REMOTE_URL = "https://github.com/CowNinja/PhronesisVault.git"

# Paths excluded from the clean CNS mirror (runtime / bulk / secrets)
EXCLUDE_PREFIXES = (
    "Operations/logs/diagnostics/",
    "Operations/logs/asar-",
    "Operations/logs/app-asar-",
    "Operations/logs/asar_check",
    "Operations/logs/content-fuse",
    "Operations/backups/",
    "Operations/session_state.sqlite",
    ".obsidian/",
    "node_modules/",
    "Digital-Twin/",  # may contain large exports; keep CNS Operations-focused
)

EXCLUDE_SUFFIXES = (
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".env",
    ".mp4",
    ".zip",
    ".7z",
    ".bak",
)

MAX_FILE_BYTES = 40 * 1024 * 1024  # hard skip single files >40MB in mirror


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: List[str], cwd: Path | None = None, timeout: int = 120) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def should_skip(rel: str, size: int) -> bool:
    rel_u = rel.replace("\\", "/")
    low = rel_u.lower()
    if size > MAX_FILE_BYTES:
        return True
    if any(low.startswith(p.lower()) for p in EXCLUDE_PREFIXES):
        return True
    if any(low.endswith(s) for s in EXCLUDE_SUFFIXES):
        return True
    if low.endswith("auth.json") or "/secrets/" in low:
        return True
    return False


def export_tree(dest: Path) -> Tuple[int, int]:
    """Archive HEAD and extract filtered tree into dest. Returns (kept, skipped)."""
    dest.mkdir(parents=True, exist_ok=True)
    code, _, err = run(["git", "-C", str(VAULT), "archive", "--format=tar", "HEAD"], timeout=180)
    # git archive writes to stdout - need binary
    try:
        r = subprocess.run(
            ["git", "-C", str(VAULT), "archive", "--format=tar", "HEAD"],
            capture_output=True,
            timeout=300,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[:300])
        tar_bytes = r.stdout
    except Exception as e:
        raise RuntimeError(f"git archive failed: {e}") from e

    kept = 0
    skipped = 0
    with tarfile.open(fileobj=BytesIO(tar_bytes), mode="r:") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                # still create dirs for kept structure via files
                continue
            rel = m.name
            if should_skip(rel, m.size or 0):
                skipped += 1
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                skipped += 1
                continue
            with target.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            kept += 1
    return kept, skipped


def largest(root: Path, n: int = 12) -> List[str]:
    rows: List[Tuple[int, str]] = []
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz >= 10 * 1024 * 1024:
                rows.append((sz, str(p.relative_to(root))))
    rows.sort(reverse=True)
    return [f"{sz/1048576:.1f}MB {rel}" for sz, rel in rows[:n]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default=DEFAULT_BRANCH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--remote-url", default=REMOTE_URL)
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).isoformat()
    errors: List[str] = []
    notes: List[str] = []

    if not (VAULT / ".git").exists():
        errors.append("vault git missing")
        _write(False, ts, args.branch, errors, notes, None)
        return 1

    head = run(["git", "-C", str(VAULT), "rev-parse", "--abbrev-ref", "HEAD"])[1]
    sha = run(["git", "-C", str(VAULT), "rev-parse", "--short", "HEAD"])[1]
    notes.append(f"source_head={head}@{sha}")
    notes.append("method=orphan_archive_v2")

    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    work = TMP_ROOT / "tree"
    repo = TMP_ROOT / "repo"
    work.mkdir(parents=True)

    log("## git archive + filter extract")
    try:
        kept, skipped = export_tree(work)
        notes.append(f"kept_files={kept}")
        notes.append(f"skipped_files={skipped}")
        log(f"OK kept={kept} skipped={skipped}")
    except Exception as e:
        errors.append(str(e)[:240])
        _write(False, ts, args.branch, errors, notes, None)
        return 1

    # Seed README for mirror branch clarity
    readme = work / "README-github-cns-mirror.md"
    readme.write_text(
        f"""# PhronesisVault CNS mirror branch

This branch is a **clean orphan tip** for offsite recovery of vault CNS markdown.
It is NOT full git history (history on master is blocked by large sqlite blobs).

- Source: `{head}@{sha}`
- Generated: {ts}
- Script: `D:/HermesData/scripts/vault_github_clean_mirror_push.py`

Do not commit `*.sqlite`. Full history rewrite requires Jeff-gated force-push
(see `Operations/Vault-GitHub-History-Purge-Runbook-2026-08-01.md`).
""",
        encoding="utf-8",
    )

    gi = work / ".gitignore"
    gi.write_text(
        "*.sqlite\n*.sqlite-wal\n*.sqlite-shm\n.env\n.env.*\nsecrets/\nauth.json\n"
        "Operations/logs/diagnostics/\nnode_modules/\n",
        encoding="utf-8",
    )

    big = largest(work)
    for row in big:
        log(f"  LARGE {row}")
        if float(row.split("MB")[0]) > 95:
            errors.append(f"file still >95MB: {row}")
    if errors:
        _write(False, ts, args.branch, errors, notes, None)
        return 2

    # Fresh repo
    if repo.exists():
        shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    # move tree into repo
    for item in work.iterdir():
        shutil.move(str(item), str(repo / item.name))

    log("## git init orphan commit")
    for cmd in (
        ["git", "init", "-b", args.branch],
        ["git", "config", "user.email", "hermes-backup@local"],
        ["git", "config", "user.name", "Hermes Backup"],
    ):
        c, so, se = run(cmd, cwd=repo, timeout=30)
        if c != 0 and cmd[1] == "init":
            errors.append(f"git init: {se or so}")
            _write(False, ts, args.branch, errors, notes, None)
            return 1

    c, so, se = run(["git", "add", "-A"], cwd=repo, timeout=180)
    if c != 0:
        errors.append(f"git add: {se or so}")
        _write(False, ts, args.branch, errors, notes, None)
        return 1

    msg = f"github-cns-mirror clean orphan tip {datetime.now().strftime('%Y%m%d-%H%M%S')} from {sha}"
    c, so, se = run(["git", "commit", "-m", msg], cwd=repo, timeout=120)
    if c != 0:
        errors.append(f"commit: {se or so}")
        _write(False, ts, args.branch, errors, notes, None)
        return 1

    c, tip, _ = run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, timeout=15)
    notes.append(f"orphan_tip={tip}")

    run(["git", "remote", "add", "origin", args.remote_url], cwd=repo, timeout=15)

    if args.dry_run:
        notes.append("dry_run_no_push")
        _write(True, ts, args.branch, errors, notes, None)
        print(json.dumps({"ok": True, "dry_run": True, "notes": notes}, indent=2))
        if not args.keep:
            shutil.rmtree(TMP_ROOT, ignore_errors=True)
        return 0

    log(f"## push -u origin {args.branch} (force tip of mirror branch only)")
    c, so, se = run(
        ["git", "push", "-u", "origin", f"HEAD:{args.branch}", "--force"],
        cwd=repo,
        timeout=300,
    )
    if c != 0:
        errors.append(f"push: {(se or so)[:300]}")
        log(f"FAIL {(se or so)[:400]}")
        _write(False, ts, args.branch, errors, notes, None)
        if not args.keep:
            shutil.rmtree(TMP_ROOT, ignore_errors=True)
        return 3

    log(f"OK pushed {args.remote_url} {args.branch} @ {tip}")
    notes.append("push_ok")
    _write(True, ts, args.branch, errors, notes, args.remote_url)
    if not args.keep:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    print(
        json.dumps(
            {
                "ok": True,
                "remote_branch": args.branch,
                "orphan_tip": tip,
                "kept": kept,
                "skipped": skipped,
                "notes": notes,
            },
            indent=2,
        )
    )
    return 0


def _write(ok: bool, ts: str, branch: str, errors: List[str], notes: List[str], url: str | None) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "ts": ts,
                "ok": ok,
                "remote_branch": branch,
                "remote_url": url or REMOTE_URL,
                "errors": errors[:20],
                "notes": notes[:40],
                "force_push_master": False,
                "method": "orphan_archive_v2",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
