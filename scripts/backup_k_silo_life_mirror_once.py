#!/usr/bin/env python3
"""Selective Personal-Digital-Silo signal mirror -> K: (budgeted, wall-clocked).

v3 (2026-08-02 cook):
  - HARD wall-clock budget (default 240s) — never hang the 4h spine.
  - Single-instance lock — kill/refuse concurrent runs (PID 7892 hung K: I/O).
  - Robocopy-first on known shallow hot paths; no full os.walk of pathological trees.
  - Partial success OK if dest has prior signal + this run copied or skipped cleanly.
  - Research: MS robocopy /MAX /XD /XF /MT /R:1 /W:1 /LEV; never MIR whole silo.

Usage:
  python D:/HermesData/scripts/backup_k_silo_life_mirror_once.py
  python D:/HermesData/scripts/backup_k_silo_life_mirror_once.py --json
  python D:/HermesData/scripts/backup_k_silo_life_mirror_once.py --budget-sec 180
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES = Path(r"D:\HermesData")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
SILO_ALT = Path(r"D:\Phronesis-Sovereign\Personal-Digital-Silo")
DEST = Path(r"K:\Hermes-Resilience\mirrors\Personal-Digital-Silo-Signal")
STATE = HERMES / "state" / "backup_k_silo_life_mirror_last.json"
LOCK = HERMES / "state" / "backup_k_silo_life_mirror.lock"
K_MAN = Path(r"K:\Hermes-Resilience\manifests\silo-signal-last.json")

# Per-file / total budgets
MAX_FILE_BYTES = 12 * 1024 * 1024  # 12MB
DEFAULT_BUDGET_SEC = 240
MAX_FILES = 8000

# Priority relative paths (files or dirs). Shallow first — indexes matter most.
PRIORITY_PATHS: List[str] = [
    "00-INDEX.md",
    "00-WORLD-INDEX.md",
    "Digital-Twin-Agent-Capabilities.md",
    "Goals-Priorities-2026-06-26.md",
    "Core-Personal/00-INDEX.md",
    "Core-Personal/Notes",
    "Core-Personal/Career",
    "Core-Personal/Family",
    "Core-Personal/Finance",
    "Core-Personal/Medical-Records",
    "Core-Personal/Projects",
    "Core-Personal/Education",
    "Core-Personal/Legal",
    "Core-Personal/Spiritual",
    "Extended",
    "Medical",
    "Medical-Records",
    "Navy-Service",
    "Digital-Footprint",
    "Archive",
    "Life-Archive",
    "Core-Personal",  # last: broad, may hit budget
]

SKIP_DIR_NAMES = {
    "node_modules",
    ".git",
    "__pycache__",
    "media",
    "Media",
    "photos",
    "Photos",
    "video",
    "Video",
    "raw",
    "Raw",
    "Audio",
    "audio",
    "_Staging-From-G-Drive",
    "_Fused",
    "test-ingest",
    "test-ingest-2026-06-25",
    "test-ingest-2026-06-26-medical-comms-tranche",
    "embeddings",
    "vectors",
    "models",
    "weights",
    "_Inbox",
}

ROBO_OK = {0, 1, 2, 3, 4, 5, 6, 7}  # robocopy success family
SIGNAL_GLOBS = ["*.md", "*.json", "*.txt", "*.csv", "*.yaml", "*.yml"]


def log(m: str) -> None:
    print(m, flush=True)


def find_silo() -> Optional[Path]:
    if SILO.is_dir():
        return SILO
    if SILO_ALT.is_dir():
        return SILO_ALT
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return str(pid) in out and "No tasks" not in out
    except Exception:
        return False


def acquire_lock(force: bool = False) -> Tuple[bool, str]:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    if LOCK.exists() and not force:
        try:
            data = json.loads(LOCK.read_text(encoding="utf-8"))
            pid = int(data.get("pid") or 0)
            age = now - float(data.get("started") or 0)
            if _pid_alive(pid) and age < 3600:
                return False, f"locked by pid={pid} age_s={age:.0f}"
            # stale lock
            log(f"WARN clearing stale silo lock pid={pid} age_s={age:.0f}")
        except Exception:
            pass
    payload = {
        "pid": os.getpid(),
        "started": now,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    LOCK.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True, "acquired"


def release_lock() -> None:
    try:
        if LOCK.exists():
            data = json.loads(LOCK.read_text(encoding="utf-8"))
            if int(data.get("pid") or 0) == os.getpid():
                LOCK.unlink(missing_ok=True)
    except Exception:
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass


def copy_file(src: Path, dst: Path, dry_run: bool) -> Tuple[str, int]:
    """Return status: copied|skipped|error, bytes."""
    try:
        sz = src.stat().st_size
    except OSError:
        return "error", 0
    if sz == 0 or sz > MAX_FILE_BYTES:
        return "skipped", 0
    if dry_run:
        return "copied", sz
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            ds = dst.stat()
            ss = src.stat()
            if ds.st_size == ss.st_size and int(ds.st_mtime) == int(ss.st_mtime):
                return "skipped", 0
        shutil.copy2(src, dst)
        return "copied", sz
    except OSError:
        return "error", 0


def robocopy_signal(
    src: Path,
    dst: Path,
    *,
    lev: int,
    timeout: int,
    dry_run: bool,
) -> Tuple[int, str]:
    if not src.is_dir():
        return 0, "not_dir"
    dst.mkdir(parents=True, exist_ok=True)
    xd: List[str] = []
    for name in sorted(SKIP_DIR_NAMES):
        xd.extend(["/XD", name])
    cmd = [
        "robocopy",
        str(src),
        str(dst),
        *SIGNAL_GLOBS,
        "/S",
        f"/MAX:{MAX_FILE_BYTES}",
        f"/LEV:{lev}",
        "/R:1",
        "/W:1",
        "/MT:4",
        "/NFL",
        "/NDL",
        "/NP",
        "/NJH",
        "/NJS",
        "/XF",
        "*.train.md",
        "*.train.meta.json",
        *xd,
    ]
    if dry_run:
        cmd.append("/L")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "")[-200:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)[:160]


def count_dest_files(limit: int = 50_000) -> Tuple[int, int]:
    n = 0
    b = 0
    if not DEST.is_dir():
        return 0, 0
    try:
        for p in DEST.rglob("*"):
            try:
                if p.is_file():
                    n += 1
                    b += p.stat().st_size
                    if n >= limit:
                        break
            except OSError:
                continue
    except OSError:
        pass
    return n, b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--budget-sec", type=int, default=int(os.environ.get("BACKUP_SILO_BUDGET_SEC", DEFAULT_BUDGET_SEC)))
    ap.add_argument("--force-lock", action="store_true")
    args = ap.parse_args()
    ts = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    budget = max(30, int(args.budget_sec))

    ok_lock, lock_msg = acquire_lock(force=args.force_lock)
    if not ok_lock:
        payload = {
            "ts": ts,
            "ok": False,
            "error": f"lock_busy: {lock_msg}",
            "partial": True,
        }
        # Do not overwrite last good receipt aggressively — sidecar only
        busy_state = HERMES / "state" / "backup_k_silo_life_mirror_busy.json"
        busy_state.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log(f"FAIL {payload['error']}")
        return 3

    try:
        root = find_silo()
        if root is None:
            payload = {"ts": ts, "ok": False, "error": "silo_root_missing"}
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            log("FAIL silo root missing")
            return 2

        DEST.mkdir(parents=True, exist_ok=True)
        copied = 0
        skipped = 0
        errors: List[str] = []
        total_b = 0
        phases: List[Dict[str, Any]] = []
        budget_hit = False

        def remaining() -> float:
            return budget - (time.time() - t0)

        # Phase A: top-level signal files (fast)
        if remaining() > 5:
            top_copied = 0
            for p in root.iterdir():
                if remaining() < 3:
                    budget_hit = True
                    break
                if not p.is_file():
                    continue
                if p.suffix.lower() not in {".md", ".json", ".txt", ".csv", ".yaml", ".yml"}:
                    continue
                if ".train." in p.name:
                    continue
                st, sz = copy_file(p, DEST / p.name, args.dry_run)
                if st == "copied":
                    copied += 1
                    total_b += sz
                    top_copied += 1
                elif st == "skipped":
                    skipped += 1
                else:
                    errors.append(f"top:{p.name}")
            phases.append({"phase": "top", "copied": top_copied})

        # Phase B: priority paths via robocopy or single-file copy
        for rel in PRIORITY_PATHS:
            if remaining() < 8:
                budget_hit = True
                break
            if copied >= MAX_FILES:
                break
            src = root / rel
            if not src.exists():
                continue
            if src.is_file():
                st, sz = copy_file(src, DEST / rel, args.dry_run)
                if st == "copied":
                    copied += 1
                    total_b += sz
                elif st == "skipped":
                    skipped += 1
                phases.append({"phase": rel, "kind": "file", "st": st})
                continue

            # directory — robocopy with short slice of remaining budget
            slice_t = max(15, min(90, int(remaining() - 5)))
            # shallower for broad trees
            lev = 3 if rel in {"Core-Personal", "Archive", "Life-Archive", "Extended"} else 5
            rc, detail = robocopy_signal(
                src, DEST / rel, lev=lev, timeout=slice_t, dry_run=args.dry_run
            )
            # robocopy 0=none, 1=copied, 2=extra, 3=...; 124=timeout
            if rc == 124:
                budget_hit = True
                phases.append({"phase": rel, "kind": "robo", "rc": 124, "timeout": True})
                # continue other lighter paths if time left
                continue
            if rc not in ROBO_OK and rc != 124:
                errors.append(f"robo {rel} rc={rc}")
            phases.append({"phase": rel, "kind": "robo", "rc": rc, "slice_s": slice_t})
            # Approximate progress: don't re-walk; mark activity
            if rc in (1, 3, 5, 7):
                copied += 1  # at least one unit of work; exact count expensive on K

        elapsed = round(time.time() - t0, 2)
        dest_n, dest_b = count_dest_files()
        # success criteria: no hard errors flood + (work done OR dest already populated)
        hard_fail = len(errors) >= 10 or dest_n == 0
        ok = not hard_fail and (copied > 0 or skipped > 0 or dest_n > 0)
        # If budget hit but dest healthy → still ok (partial)
        partial = budget_hit

        idx = {
            "ts": ts,
            "source": str(root),
            "copied": copied,
            "skipped": skipped,
            "total_bytes": total_b,
            "errors": errors[:20],
            "budget_files": MAX_FILES,
            "budget_sec": budget,
            "elapsed_sec": elapsed,
            "budget_hit": budget_hit,
            "partial": partial,
            "dest_files": dest_n,
            "dest_bytes": dest_b,
            "phases": phases[:40],
            "version": 3,
        }
        if not args.dry_run:
            try:
                (DEST / "00-SIGNAL-MIRROR-MANIFEST.json").write_text(
                    json.dumps(idx, indent=2), encoding="utf-8"
                )
            except OSError as e:
                errors.append(f"manifest: {e}")

        payload = {
            "ts": ts,
            "ok": ok,
            **idx,
            "dest": str(DEST),
            "dry_run": args.dry_run,
            "error_count": len(errors),
        }
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            K_MAN.parent.mkdir(parents=True, exist_ok=True)
            K_MAN.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            log(
                f"DONE ok={ok} copied~={copied} skipped={skipped} "
                f"dest_files={dest_n} elapsed={elapsed}s budget_hit={budget_hit} errors={len(errors)}"
            )
        return 0 if ok else 1
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
