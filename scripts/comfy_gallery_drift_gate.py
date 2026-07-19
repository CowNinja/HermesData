#!/usr/bin/env python3
"""Weekly no_agent Comfy gallery drift gate.

Runs dry-run dedup (--scope both) + light FS↔DB count check.
Silent (empty stdout, exit 0) when reclaim_mb < THRESHOLD and counts align.
One-line alert on stdout when drift exceeds threshold (cron delivers).

Never --apply. Never hard-delete.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
LOGS = HERMES / "logs"
PURGE = SCRIPTS / "comfy_purge_duplicate_images.py"
GALLERY_IMAGES = Path(r"D:\ComfyUI\gallery\images")
GALLERY_DB = Path(r"D:\ComfyUI\gallery\gallery.db")
OUT_JSON = LOGS / "comfy_gallery_drift_gate_latest.json"
JSONL = LOGS / "comfy_gallery_drift_gate.jsonl"

# Alert if reclaim at or above this (MB). Below = silent healthy.
RECLAIM_MB_THRESHOLD = 50.0
# Alert if |fs_images - db_rows| exceeds this
COUNT_DELTA_THRESHOLD = 5


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_images() -> int:
    if not GALLERY_IMAGES.is_dir():
        return -1
    n = 0
    for p in GALLERY_IMAGES.iterdir():
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            n += 1
    return n


def count_db() -> int:
    if not GALLERY_DB.is_file():
        return -1
    con = sqlite3.connect(str(GALLERY_DB))
    try:
        return int(con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
    finally:
        con.close()


def run_dry_run(timeout: int = 900) -> dict:
    cmd = [sys.executable, str(PURGE), "--scope", "both", "--top", "5"]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(HERMES),
    )
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    # Prefer newest report written by purge
    reps = sorted(LOGS.glob("comfy_dedup_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    report: dict = {}
    if reps:
        try:
            report = json.loads(reps[0].read_text(encoding="utf-8"))
        except Exception as e:
            report = {"parse_error": str(e), "path": str(reps[0])}
    return {
        "exit": r.returncode,
        "stdout_tail": out[-1500:],
        "report_path": str(reps[0]) if reps else None,
        "reclaim_mb": float(report.get("reclaim_mb") or 0.0),
        "reclaim_bytes": int(report.get("reclaim_bytes") or 0),
        "dup_groups": int(report.get("dup_groups") or 0),
        "files_to_delete": int(report.get("files_to_delete") or 0),
        "total_images": int(report.get("total_images") or 0),
        "unique_hashes": int(report.get("unique_hashes") or 0),
    }


def main() -> int:
    ts = utc()
    fs_n = count_images()
    db_n = count_db()
    delta = abs(fs_n - db_n) if fs_n >= 0 and db_n >= 0 else 9999

    try:
        dry = run_dry_run()
    except subprocess.TimeoutExpired:
        dry = {
            "exit": 124,
            "reclaim_mb": 0.0,
            "reclaim_bytes": 0,
            "dup_groups": 0,
            "files_to_delete": 0,
            "error": "TIMEOUT",
        }
    except Exception as e:
        dry = {
            "exit": 1,
            "reclaim_mb": 0.0,
            "reclaim_bytes": 0,
            "dup_groups": 0,
            "files_to_delete": 0,
            "error": f"{type(e).__name__}: {e}",
        }

    reclaim = float(dry.get("reclaim_mb") or 0.0)
    reasons: list[str] = []
    if dry.get("exit") not in (0, None) or dry.get("error"):
        reasons.append(f"dry_run_fail exit={dry.get('exit')} err={dry.get('error')}")
    if reclaim >= RECLAIM_MB_THRESHOLD:
        reasons.append(f"reclaim_mb={reclaim:.1f}>={RECLAIM_MB_THRESHOLD}")
    if delta > COUNT_DELTA_THRESHOLD:
        reasons.append(f"fs_db_delta={delta} fs={fs_n} db={db_n}")

    alert = bool(reasons)
    payload = {
        "ts": ts,
        "alert": alert,
        "reasons": reasons,
        "fs_images": fs_n,
        "db_rows": db_n,
        "fs_db_delta": delta,
        "reclaim_mb": reclaim,
        "threshold_mb": RECLAIM_MB_THRESHOLD,
        "count_delta_threshold": COUNT_DELTA_THRESHOLD,
        "dry": {k: dry.get(k) for k in (
            "exit", "reclaim_mb", "reclaim_bytes", "dup_groups", "files_to_delete",
            "total_images", "unique_hashes", "report_path", "error",
        ) if k in dry or dry.get(k) is not None},
    }

    LOGS.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")

    if alert:
        # One line for cron delivery
        print(
            "Comfy gallery DRIFT: "
            + "; ".join(reasons)
            + f" | dry-run reclaim={reclaim:.1f}MB groups={dry.get('dup_groups')} "
            + f"drop={dry.get('files_to_delete')} fs={fs_n} db={db_n} "
            + f"log={OUT_JSON}"
        )
        return 0  # alert via stdout; don't fail cron as hard error
    # Silent when healthy
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
