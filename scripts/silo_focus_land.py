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
WALK_CURSOR = Path(r"D:\HermesData\state\g_to_k_walk_cursor.json")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-drain-receipt-latest.md")
SCRIPTS = Path(r"D:\HermesData\scripts")
# 2026-07-26: pct-only gate skipped Ballas (~212 residual) and Google Drive (~564)
# because both sat just over 97%. Prefer absolute residual + walk_cursor complete.
MIN_RESIDUAL_ABS = 8
RESIDUAL_PCT_FLOOR = 0.003  # 0.3% of disk still counts as incomplete
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
    """Read latest APPLY drain receipt for copied/skipped/planned + walk stats.

    Ignores dry-run receipts (separate file since 2026-07-19) so empty-plan
    auto-advance never fires on probe waves.

    2026-07-26: drain receipt uses ASCII ' | ' separators; older parser only
    matched middle-dot '·' so empty-plan never fired (GDrive thrash).
    """
    out: dict = {
        "copied": None,
        "skipped": None,
        "planned": None,
        "mode": None,
        "walked": None,
        "known_skip": None,
        "emitted": None,
        "wrap": None,
    }
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
        # Accept · or | or plain spaces between fields
        m = re.search(
            r"\*\*Copied:\*\*\s*(\d+)\s*[·|]\s*\*\*Skipped:\*\*\s*(\d+)\s*[·|]\s*\*\*Planned rows:\*\*\s*(\d+)",
            text,
        )
        if not m:
            # ultra-loose fallback
            m = re.search(
                r"Copied:\*\*\s*(\d+).*?Skipped:\*\*\s*(\d+).*?Planned rows:\*\*\s*(\d+)",
                text,
                re.S,
            )
        if m:
            out["copied"] = int(m.group(1))
            out["skipped"] = int(m.group(2))
            out["planned"] = int(m.group(3))
            out["mode"] = mode or "APPLY"
        wm = re.search(
            r"walked=(\d+)\s+known_skip=(\d+)\s+new=(\d+)\s+emitted=(\d+)\s+wrap=(\w+)",
            text,
        )
        if wm:
            out["walked"] = int(wm.group(1))
            out["known_skip"] = int(wm.group(2))
            out["new"] = int(wm.group(3))
            out["emitted"] = int(wm.group(4))
            out["wrap"] = wm.group(5).lower() in ("true", "1", "yes")
    except Exception:
        pass
    return out


def _walk_cursor_complete(path: str) -> bool:
    """True when g_to_k_walk_cursor marks this root complete (empty-wrap/catalog done)."""
    if not WALK_CURSOR.is_file():
        return False
    try:
        data = json.loads(WALK_CURSOR.read_text(encoding="utf-8"))
        roots = data.get("roots") or {}
        want = str(Path(path)).replace("/", "\\").rstrip("\\").lower()
        for k, v in roots.items():
            kn = str(k).replace("/", "\\").rstrip("\\").lower()
            if kn == want and isinstance(v, dict) and v.get("complete") is True:
                return True
        return False
    except Exception:
        return False


def _mark_walk_complete(path: str, reason: str) -> bool:
    """Mark walk cursor root complete so residual gate / board stop thrashing it."""
    if not WALK_CURSOR.is_file():
        return False
    try:
        data = json.loads(WALK_CURSOR.read_text(encoding="utf-8"))
        roots = dict(data.get("roots") or {})
        want = str(Path(path)).replace("/", "\\").rstrip("\\").lower()
        hit = None
        for k in list(roots.keys()):
            kn = str(k).replace("/", "\\").rstrip("\\").lower()
            if kn == want:
                hit = k
                break
        if hit is None:
            # create entry under canonical path form
            hit = str(Path(path)).replace("/", "\\")
            roots[hit] = {}
        ent = dict(roots.get(hit) or {})
        ent["complete"] = True
        ent["completed_at"] = utc()
        ent["complete_reason"] = (reason or "focus_auto_advance")[:400]
        ent["at"] = utc()
        roots[hit] = ent
        data["roots"] = roots
        data["updated"] = utc()
        if atomic_write_json is not None:
            atomic_write_json(WALK_CURSOR, data, indent=2)
        else:
            WALK_CURSOR.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _meaningful_residual(disk_n: int, reg_n: int, threshold: float) -> tuple[bool, int, float]:
    """Return (still_incomplete, residual, pct).

    Industry lesson (NiFi backpressure / Celery ack): never treat a large tree as
    done on percentage alone — absolute residual is the real backlog signal.
    disk_n==0 is unknown (not complete).
    """
    if disk_n <= 0:
        return True, -1, 0.0  # unknown — do not auto-skip
    residual = max(0, int(disk_n) - int(reg_n))
    pct = (reg_n / disk_n) if disk_n else 1.0
    # Over-registry (reg>disk) => residual 0, complete for land purposes
    if residual <= 0:
        return False, 0, pct
    floor = max(MIN_RESIDUAL_ABS, int(RESIDUAL_PCT_FLOOR * disk_n))
    if residual > floor:
        return True, residual, pct
    if pct < threshold:
        return True, residual, pct
    return False, residual, pct


def reconcile_queue(threshold: float = 0.97) -> dict:
    """Mark walk-complete + residual-gate-done roots land_complete (full pass).

    top_incomplete() returns at the first still-open root, so lower-priority
    walk-complete items (e.g. Misc_Other) never got synced while GDrive/arch
    blocked the head. Call this each focus dry-run / tick start.

    Research: Celery inspect + NiFi backlog — reconcile side state so the
    priority head is real work, not stale open rows.
    """
    if not QUEUE.is_file():
        return {"ok": False, "err": "no_queue"}
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    items = sorted(
        data.get("land_priority_queue") or [],
        key=lambda x: -int(x.get("priority") or 0),
    )
    cache = load_cache()
    con = sqlite3.connect(str(REG), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    walk_done: list[str] = []
    residual_done: list[str] = []
    still_open: list[dict] = []
    try:
        for it in items:
            if it.get("mode") in ("catalog_only", "never", "land_complete"):
                continue
            path = it.get("path")
            iid = str(it.get("id") or "")
            if not path:
                continue
            if not Path(path).exists():
                continue
            if _walk_cursor_complete(path):
                if iid and mark_queue_complete(iid, "walk_cursor.complete=True reconcile"):
                    walk_done.append(iid)
                continue
            root = Path(path)
            root_n = str(root).replace("/", "\\").rstrip("\\")
            reg_n = con.execute(
                "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?",
                (root_n + "\\" + "%",),
            ).fetchone()[0]
            disk_n = disk_file_count(root, cache)
            still, residual, pct = _meaningful_residual(disk_n, reg_n, threshold)
            if not still:
                if iid:
                    mark_queue_complete(
                        iid,
                        f"residual_gate reconcile residual={residual} "
                        f"pct={round(100 * pct, 1)} disk={disk_n}",
                    )
                    residual_done.append(iid)
                # 2026-07-26: residual_gate closed queue but left walk cursor open
                # (Images/Safari board thrash). Always sync walk complete here.
                try:
                    _mark_walk_complete(
                        str(path),
                        f"residual_gate reconcile residual={residual} "
                        f"pct={round(100 * pct, 1)} disk={disk_n}",
                    )
                except Exception as exc:
                    print(
                        json.dumps(
                            {
                                "walk_complete_warn": f"{iid}:{type(exc).__name__}:{exc}"[
                                    :200
                                ]
                            }
                        )
                    )
                continue
            still_open.append(
                {
                    "id": iid,
                    "path": path,
                    "priority": it.get("priority"),
                    "reg": reg_n,
                    "disk": disk_n,
                    "residual": residual,
                    "pct": round(100 * pct, 1),
                }
            )
    finally:
        con.close()
    out = {
        "at": utc(),
        "walk_done": walk_done,
        "residual_done": residual_done,
        "still_open": still_open,
        "n_open": len(still_open),
    }
    print(json.dumps({"reconcile_queue": out}, indent=2))
    return out


def top_incomplete(threshold: float = 0.97) -> tuple[str | None, dict]:
    # Full reconcile first so stale walk-complete rows leave the open set
    recon = reconcile_queue(threshold=threshold)
    still = recon.get("still_open") or []
    if not still:
        return None, {
            "done": True,
            "auto_completed_ids": (recon.get("walk_done") or [])
            + (recon.get("residual_done") or []),
        }
    top = still[0]
    top = dict(top)
    top["auto_completed_ids"] = (recon.get("walk_done") or []) + (
        recon.get("residual_done") or []
    )
    return top.get("path"), top


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
    # Empty-plan / residual-exhausted auto-advance.
    # Research: Celery ack + NiFi backpressure — do not requeue work that produced
    # zero durable progress after a full skip-pass (poison / already-known tree).
    receipt = parse_drain_receipt()
    copied = receipt.get("copied")
    planned = receipt.get("planned")
    walked = int(receipt.get("walked") or 0)
    known_skip = int(receipt.get("known_skip") or 0)
    empty = (
        copied == 0
        and planned == 0
        and r.returncode == 0
    )
    # residual_exhausted: large walk, >=98% already known, zero copies, AND no
    # planned apply rows. planned>0 with copied=0 is failure (path ERR / hash
    # skip-all after filter) — do NOT auto-complete; operator/fix can retry.
    # Research: Celery reject vs ack — only ack when broker work is truly done.
    # 2026-07-26: tiny roots (Images=2, Safari=1) never hit walked>=50; still
    # residual-exhausted when the full walk produced zero durable plan/copy.
    # Research: Celery ack tiny tasks — complete when broker work is done, not
    # only when batch size exceeds an arbitrary floor.
    residual_exhausted = (
        r.returncode == 0
        and copied == 0
        and planned == 0
        and walked >= 1
        and known_skip >= int(walked * 0.98)
        and (walked >= 50 or known_skip >= walked)
    )
    st = load_empty_state()
    key = str(info.get("id") or path)
    if empty or residual_exhausted:
        ent = st.get(key) or {"strikes": 0}
        ent["strikes"] = int(ent.get("strikes") or 0) + 1
        ent["at"] = utc()
        ent["last_receipt"] = receipt
        ent["reason"] = "empty_plan" if empty else "residual_exhausted"
        st[key] = ent
        save_empty_state(st)
        # residual_exhausted advances on 1 strike (full tree already known);
        # classic empty_plan still needs N strikes (default 2).
        need = 1 if residual_exhausted else args.empty_plan_strikes
        if ent["strikes"] >= need:
            note = (
                f"{ent['reason']} x{ent['strikes']} "
                f"copied={copied} planned={planned} walked={walked} "
                f"known_skip={known_skip} receipt={receipt}"
            )
            ok = mark_queue_complete(str(info.get("id") or ""), note)
            # Mark walk cursor complete so residual gate stops re-picking this root
            try:
                _mark_walk_complete(path, note)
            except Exception as exc:
                print(json.dumps({"walk_complete_warn": str(exc)[:160]}))
            print(
                json.dumps(
                    {
                        "auto_advance": ok,
                        "id": info.get("id"),
                        "strikes": ent["strikes"],
                        "reason": ent["reason"],
                        "need": need,
                        "receipt": receipt,
                    },
                    indent=2,
                )
            )
            st[key] = {"strikes": 0, "at": utc(), "advanced": ok, "reason": ent["reason"]}
            save_empty_state(st)
    else:
        # productive wave (copied>0) — reset strikes
        if copied and int(copied) > 0:
            if key in st and int((st.get(key) or {}).get("strikes") or 0) > 0:
                st[key] = {
                    "strikes": 0,
                    "at": utc(),
                    "last_receipt": receipt,
                    "reset": "productive_copy_wave",
                }
                save_empty_state(st)
        # skip-only mid-tree without exhaustion: keep strikes (do NOT reset)
    return int(r.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
