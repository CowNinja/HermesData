#!/usr/bin/env python3
"""Poison recurrence guard — keep vault git free of runtime DBs / huge blobs.

Checks (read-only by default):
  - working tree / index tracked *.sqlite*
  - staged files >50MB or blocked suffixes
  - tip tree blobs >50MB on HEAD
  - .gitignore contains sqlite patterns

Optional:
  --fix-gitignore   ensure ignore rules present
  --unstaged-blocked unstage blocked paths from index

Writes D:/HermesData/state/vault_poison_guard_last.json
Exit 0 clean/warn-only, 1 if poison present on tip or index.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
STATE = HERMES / "state" / "vault_poison_guard_last.json"
BLOCK_SUFFIXES = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")
MAX_BLOB = 50 * 1024 * 1024
GITIGNORE_SNIP = """
# Hermes poison guard — runtime DBs never in git
*.sqlite
*.sqlite-wal
*.sqlite-shm
**/session_state.sqlite
Operations/*.sqlite
Operations/**/*.sqlite
"""


def run(args: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(VAULT), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix-gitignore", action="store_true")
    ap.add_argument("--unstage-blocked", action="store_true")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    issues: List[str] = []
    warns: List[str] = []
    notes: List[str] = []

    if not (VAULT / ".git").exists():
        payload = {"ts": ts, "ok": False, "errors": ["vault not a git repo"]}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1

    # tracked sqlite
    c, out, _ = run(["ls-files", "*.sqlite", "*.sqlite-wal", "*.sqlite-shm"], timeout=30)
    tracked = [ln for ln in (out or "").splitlines() if ln.strip()]
    if tracked:
        issues.append(f"tracked_sqlite={tracked[:20]}")
        if args.unstage_blocked:
            for p in tracked:
                run(["rm", "--cached", "--ignore-unmatch", "--", p], timeout=15)
            notes.append("attempted_untrack_sqlite")

    # staged large / blocked
    c, staged, _ = run(["diff", "--cached", "--name-only"], timeout=30)
    blocked_staged = []
    for line in (staged or "").splitlines():
        low = line.lower().replace("\\", "/")
        if any(low.endswith(s) for s in BLOCK_SUFFIXES):
            blocked_staged.append(line)
    if blocked_staged:
        issues.append(f"staged_blocked={blocked_staged[:20]}")
        if args.unstage_blocked:
            for p in blocked_staged:
                run(["reset", "-q", "HEAD", "--", p], timeout=10)
            notes.append("unstaged_blocked")

    # tip blobs >50MB
    c, out, err = run(["rev-list", "--objects", "HEAD"], timeout=180)
    big: List[str] = []
    if c == 0 and out:
        # pipe via python
        import subprocess as sp

        p1 = sp.run(
            ["git", "-C", str(VAULT), "rev-list", "--objects", "HEAD"],
            capture_output=True,
            timeout=180,
        )
        p2 = sp.run(
            [
                "git",
                "-C",
                str(VAULT),
                "cat-file",
                "--batch-check=%(objecttype) %(objectname) %(objectsize) %(rest)",
            ],
            input=p1.stdout,
            capture_output=True,
            timeout=180,
        )
        for line in (p2.stdout or b"").decode("utf-8", "replace").splitlines():
            parts = line.split(maxsplit=3)
            if len(parts) >= 3 and parts[0] == "blob":
                try:
                    sz = int(parts[2])
                except ValueError:
                    continue
                if sz > MAX_BLOB:
                    name = parts[3] if len(parts) > 3 else parts[1]
                    big.append(f"{sz/1024/1024:.1f}MB {name}")
    if big:
        issues.append(f"tip_big_blobs={big[:15]}")

    # gitignore
    gi = VAULT / ".gitignore"
    text = gi.read_text(encoding="utf-8", errors="replace") if gi.exists() else ""
    need = ["*.sqlite", "session_state.sqlite"]
    missing = [n for n in need if n not in text]
    if missing:
        warns.append(f"gitignore_missing={missing}")
        if args.fix-gitignore:
            with gi.open("a", encoding="utf-8") as f:
                f.write("\n" + GITIGNORE_SNIP)
            notes.append("gitignore_appended")

    # origin master big blobs (post-purge should be empty)
    c, out, _ = run(["fetch", "origin", "master"], timeout=120)
    notes.append(f"fetch_master_rc={c}")
    p1 = subprocess.run(
        ["git", "-C", str(VAULT), "rev-list", "--objects", "origin/master"],
        capture_output=True,
        timeout=180,
    )
    p2 = subprocess.run(
        [
            "git",
            "-C",
            str(VAULT),
            "cat-file",
            "--batch-check=%(objecttype) %(objectname) %(objectsize) %(rest)",
        ],
        input=p1.stdout,
        capture_output=True,
        timeout=180,
    )
    origin_big = []
    for line in (p2.stdout or b"").decode("utf-8", "replace").splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) >= 3 and parts[0] == "blob":
            try:
                sz = int(parts[2])
            except ValueError:
                continue
            if sz > MAX_BLOB:
                name = parts[3] if len(parts) > 3 else "?"
                origin_big.append(f"{sz/1024/1024:.1f}MB {name}")
    if origin_big:
        issues.append(f"origin_master_big_blobs={origin_big[:10]}")
    else:
        notes.append("origin_master_clean_of_50mb_blobs")

    ok = len(issues) == 0
    payload = {
        "ts": ts,
        "ok": ok,
        "issues": issues,
        "warns": warns,
        "notes": notes,
        "tracked_sqlite_count": len(tracked),
        "tip_big_count": len(big),
        "origin_big_count": len(origin_big),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"POISON_GUARD ok={ok} issues={len(issues)} warns={len(warns)}")
        for i in issues:
            print(f"  ISSUE: {i[:200]}")
        for w in warns:
            print(f"  WARN: {w[:200]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
