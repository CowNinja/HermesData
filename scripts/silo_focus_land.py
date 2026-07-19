#!/usr/bin/env python3
"""Focus land: drain only the highest-priority incomplete folder.

Self-improve efficiency: don't re-walk completed trees; put full throttle
on the current top item (Medical→Alex→Booksbloom…→Jeff gold subpaths).
Caches disk file counts to avoid full-tree scans every tick.

2026-07-18: empty-plan auto-advance — if drain copies 0 (remainder is
catalog/junk/already-on-K), mark source land_complete after N strikes so
chef advances (disk% can stall below 97% when many files are catalog-only).
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

QUEUE = Path(r"D:\HermesData\config\land_priority_queue.json")
REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
CACHE = Path(r"D:\HermesData\state\land_folder_disk_cache.json")
EMPTY_STATE = Path(r"D:\HermesData\state\focus_land_empty_plan.json")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-drain-receipt-latest.md")
SCRIPTS = Path(r"D:\HermesData\scripts")
# Land drain child must be python.exe — nested pythonw under orch PIPEs fails
# silent exit 1 (2026-07-19 repro). See windows_subprocess.prefer_python_console.
try:
    from windows_subprocess import prefer_python_console  # type: ignore

    PY = prefer_python_console(sys.executable)
except Exception:  # pragma: no cover
    _p = Path(sys.executable)
    if _p.name.lower() == "pythonw.exe" and _p.with_name("python.exe").is_file():
        PY = str(_p.with_name("python.exe"))
    else:
        PY = sys.executable
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
CACHE_TTL_S = 6 * 3600  # re-count every 6h


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_cache() -> dict:
    if CACHE.is_file():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(CACHE, c, indent=2)
    else:
        CACHE.write_text(json.dumps(c, indent=2), encoding="utf-8")


def disk_file_count(root: Path, cache: dict) -> int:
    key = str(root)
    now = time.time()
    ent = cache.get(key) or {}
    if ent.get("n") is not None and (now - float(ent.get("at") or 0)) < CACHE_TTL_S:
        return int(ent["n"])
    n = 0
    for i, fp in enumerate(root.rglob("*")):
        if fp.is_file():
            n += 1
        if i > 250000:
            break
    cache[key] = {"n": n, "at": now}
    save_cache(cache)
    return n


def load_empty_state() -> dict:
    if EMPTY_STATE.is_file():
        try:
            return json.loads(EMPTY_STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_empty_state(d: dict) -> None:
    EMPTY_STATE.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(EMPTY_STATE, d, indent=2)
    else:
        EMPTY_STATE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def mark_queue_complete(item_id: str, note: str) -> bool:
    """Set mode=land_complete on queue item id (timestamped bak)."""
    if not QUEUE.is_file() or not item_id:
        return False
    try:
        bak = QUEUE.with_suffix(
            QUEUE.suffix + f".bak-focus-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        raw = QUEUE.read_text(encoding="utf-8")
        if not bak.exists():
            bak.write_text(raw, encoding="utf-8")
        data = json.loads(raw)
        changed = False
        for it in data.get("land_priority_queue") or []:
            if it.get("id") == item_id:
                it["mode"] = "land_complete"
                it["completed_at"] = utc()
                prev = (it.get("note") or "").strip()
                it["note"] = (prev + f" | auto-complete: {note}").strip(" |")
                it["updated"] = "2026-07-18"
                changed = True
                break
        if changed:
            data["updated"] = utc()
            if atomic_write_json is not None:
                atomic_write_json(QUEUE, data, indent=2)
            else:
                QUEUE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return changed
    except Exception:
        return False


def parse_drain_receipt() -> dict:
    """Read latest APPLY drain receipt for copied/skipped/planned.

    Ignores dry-run receipts (separate file since 2026-07-19) so empty-plan
    auto-advance never fires on probe waves.
    """
    out = {"copied": None, "skipped": None, "planned": None, "mode": None}
    if not RECEIPT.is_file():
        return out
    try:
        text = RECEIPT.read_text(encoding="utf-8", errors="replace")
        # Refuse dry-run content if it ever lands on the apply path again.
        mode_m = re.search(r"\*\*Mode:\*\*\s*(\S+)", text)
        mode = (mode_m.group(1) if mode_m else "").strip().upper()
        out["mode"] = mode or None
        if mode and mode != "APPLY":
            return out
        m = re.search(
            r"\*\*Copied:\*\*\s*(\d+)\s*·\s*\*\*Skipped:\*\*\s*(\d+)\s*·\s*\*\*Planned rows:\*\*\s*(\d+)",
            text,
        )
        if m:
            out = {
                "copied": int(m.group(1)),
                "skipped": int(m.group(2)),
                "planned": int(m.group(3)),
                "mode": mode or "APPLY",
            }
    except Exception:
        pass
    return out


def top_incomplete(threshold: float = 0.97) -> tuple[str | None, dict]:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    items = sorted(
        data.get("land_priority_queue") or [],
        key=lambda x: -int(x.get("priority") or 0),
    )
    cache = load_cache()
    con = sqlite3.connect(str(REG), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        for it in items:
            if it.get("mode") in ("catalog_only", "never", "land_complete"):
                continue
            path = it.get("path")
            if not path or not Path(path).exists():
                continue
            root = Path(path)
            root_n = str(root).replace("/", "\\").rstrip("\\")
            reg_n = con.execute(
                "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?",
                (root_n + "\\" + "%",),
            ).fetchone()[0]
            disk_n = disk_file_count(root, cache)
            pct = (reg_n / disk_n) if disk_n else 1.0
            info = {
                "id": it.get("id"),
                "path": path,
                "priority": it.get("priority"),
                "reg": reg_n,
                "disk": disk_n,
                "pct": round(100 * pct, 1),
            }
            if pct < threshold:
                return path, info
        return None, {"done": True}
    finally:
        con.close()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--empty-plan-strikes",
        type=int,
        default=2,
        help="consecutive empty/zero-copy waves before auto land_complete",
    )
    args = ap.parse_args()

    path, info = top_incomplete()
    print(json.dumps({"focus": info}, indent=2))
    if not path:
        print(json.dumps({"status": "all_priority_complete"}))
        return 0
    if args.dry_run:
        return 0
    # Refuse to spawn a second drain if one is already land-writing (orphan
    # protection). Drain itself also singleton-locks; this is the fast path.
    try:
        rps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { "
                "$_.Name -like 'python*' -and $_.CommandLine -like '*g_to_k_safe_drain.py*' } "
                "| Measure-Object | Select-Object -ExpandProperty Count",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_NO_WINDOW,
        )
        raw_n = (rps.stdout or "0").strip().splitlines()
        n_s = (raw_n[-1] if raw_n else "0").strip() or "0"
        n_drain = int(n_s) if n_s.isdigit() else 0
        # count includes nothing yet; if >=1 another writer is live
        if n_drain >= 1:
            print(
                json.dumps(
                    {
                        "status": "skip_drain_already_running",
                        "drain_procs": n_drain,
                        "focus": info,
                    },
                    indent=2,
                )
            )
            return 0
    except Exception as e:
        print(json.dumps({"warn": f"drain_precheck_failed:{type(e).__name__}:{e}"}))
    cmd = [
        PY,
        str(SCRIPTS / "g_to_k_safe_drain.py"),
        "--apply",
        "--limit",
        str(args.limit),
        "--source",
        path,
    ]
    print(json.dumps({"drain_cmd_python": PY, "limit": args.limit, "source": path}))
    # Capture + forward: orch only keeps last 4k of worker out; still better than
    # silent nested-pythonw death. CREATE_NO_WINDOW avoids console flash with python.exe.
    try:
        r = subprocess.run(
            cmd,
            cwd=str(SCRIPTS),
            capture_output=True,
            text=True,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        print(json.dumps({"status": "drain_spawn_failed", "error": f"{type(e).__name__}: {e}"}))
        return 1
    if r.stdout:
        sys.stdout.write(r.stdout if r.stdout.endswith("\n") else r.stdout + "\n")
    if r.stderr:
        sys.stderr.write(r.stderr if r.stderr.endswith("\n") else r.stderr + "\n")
    print(
        json.dumps(
            {
                "drain_exit": int(r.returncode or 0),
                "drain_stdout_chars": len(r.stdout or ""),
                "drain_stderr_chars": len(r.stderr or ""),
            }
        )
    )
    # Empty-plan auto-advance only when NOTHING left to plan (not skip-heavy mid-tree).
    # Skip-only waves reset progress tracking but do NOT complete — next wave may
    # still find landable files deeper (hash/skip_sources catch-up).
    receipt = parse_drain_receipt()
    empty = (
        receipt.get("copied") == 0
        and receipt.get("planned") == 0
        and r.returncode == 0
    )
    st = load_empty_state()
    key = str(info.get("id") or path)
    if empty:
        ent = st.get(key) or {"strikes": 0}
        ent["strikes"] = int(ent.get("strikes") or 0) + 1
        ent["at"] = utc()
        ent["last_receipt"] = receipt
        ent["reason"] = "empty_plan"
        st[key] = ent
        save_empty_state(st)
        if ent["strikes"] >= args.empty_plan_strikes:
            note = f"empty_plan x{ent['strikes']} receipt={receipt}"
            ok = mark_queue_complete(str(info.get("id") or ""), note)
            print(
                json.dumps(
                    {
                        "auto_advance": ok,
                        "id": info.get("id"),
                        "strikes": ent["strikes"],
                        "receipt": receipt,
                    },
                    indent=2,
                )
            )
            st[key] = {"strikes": 0, "at": utc(), "advanced": ok}
            save_empty_state(st)
    else:
        # productive or skip-catchup wave — reset empty strikes
        if key in st and int((st.get(key) or {}).get("strikes") or 0) > 0:
            st[key] = {
                "strikes": 0,
                "at": utc(),
                "last_receipt": receipt,
                "reset": "productive_or_skip_wave",
            }
            save_empty_state(st)
    return int(r.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
