#!/usr/bin/env python3
"""Scoreboard v2 — efficiency + effectiveness metrics for the silo factory.

Barney board + deep metrics. $0 Grok. Writes:
  state/silo_scoreboard_v2.json
  Operations/logs/silo-scoreboard-v2-latest.md
  append state/silo_scoreboard_history.jsonl
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:\HermesData\state")
REG = STATE / "ingest_registry.sqlite3"
OCR = STATE / "ocr_backlog.sqlite3"
CONT = STATE / "silo_continuous_state.json"
QUEUE = Path(r"D:\HermesData\config\land_priority_queue.json")
OUT_JSON = STATE / "silo_scoreboard_v2.json"
OUT_HIST = STATE / "silo_scoreboard_history.jsonl"
OUT_MD = Path(r"D:\PhronesisVault\Operations\logs\silo-scoreboard-v2-latest.md")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def vram_ram() -> dict:
    out = {"vram_mib": None, "ram_pct": None}
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode == 0:
            out["vram_mib"] = int(r.stdout.strip().splitlines()[0].strip())
    except Exception:
        pass
    try:
        import psutil  # type: ignore

        out["ram_pct"] = float(psutil.virtual_memory().percent)
    except Exception:
        pass
    return out


def chef_count() -> int:
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*silo_continuous_loop.py*' } | Measure-Object).Count",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return int((r.stdout or "0").strip() or "0")
    except Exception:
        return -1


def folder_stats(con: sqlite3.Connection, root: str) -> dict:
    # Prefer shared disk cache from focus_land (self-improve efficiency)
    _cache_p = Path(r"D:/HermesData/state/land_folder_disk_cache.json")
    _disk_cached = None
    if _cache_p.is_file():
        try:
            _c = json.loads(_cache_p.read_text(encoding="utf-8"))
            _ent = _c.get(str(Path(root))) or _c.get(root)
            if _ent and _ent.get("n") is not None:
                _disk_cached = int(_ent["n"])
        except Exception:
            pass

    root_n = root.replace("/", "\\").rstrip("\\")
    # count files on disk (cap walk cost)
    src = Path(root)
    disk_n = 0
    disk_bytes = 0
    if _disk_cached is not None:
        disk_n = _disk_cached
    elif src.is_dir():
        for i, p in enumerate(src.rglob("*")):
            if not p.is_file():
                continue
            try:
                disk_n += 1
                disk_bytes += p.stat().st_size
            except OSError:
                pass
            if i > 200000:
                break
    reg_n = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?",
        (root_n + "\\%",),
    ).fetchone()[0]
    pct = round(100.0 * reg_n / disk_n, 1) if disk_n else None
    return {
        "path": root,
        "disk_files": disk_n,
        "disk_gb": round(disk_bytes / (1024**3), 2),
        "registry": reg_n,
        "pct": pct,
    }


def throughput(hist: list[dict]) -> dict:
    if len(hist) < 2:
        return {"files_per_hour": None, "samples": len(hist)}
    a, b = hist[0], hist[-1]
    try:
        t0 = datetime.fromisoformat(a["at"].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(b["at"].replace("Z", "+00:00"))
        hours = max((t1 - t0).total_seconds() / 3600.0, 1 / 60)
        dreg = (b.get("registry") or 0) - (a.get("registry") or 0)
        docr = (b.get("ocr_ok") or 0) - (a.get("ocr_ok") or 0)
        return {
            "files_per_hour": round(dreg / hours, 1),
            "ocr_per_hour": round(docr / hours, 1),
            "hours_span": round(hours, 2),
            "samples": len(hist),
        }
    except Exception:
        return {"files_per_hour": None, "samples": len(hist)}


def main() -> int:
    t0 = time.time()
    con = sqlite3.connect(str(REG), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    reg = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    uniq = con.execute(
        "SELECT COUNT(DISTINCT sha256) FROM ingest WHERE sha256 IS NOT NULL AND sha256!=''"
    ).fetchone()[0]
    proc = dict(
        con.execute(
            "SELECT COALESCE(process_status,'null'), COUNT(*) FROM ingest GROUP BY process_status"
        ).fetchall()
    )

    ocr = {}
    if OCR.is_file():
        try:
            oc = sqlite3.connect(str(OCR), timeout=10)
            ocr = dict(
                oc.execute(
                    "SELECT status, COUNT(*) FROM ocr_queue GROUP BY status"
                ).fetchall()
            )
            oc.close()
        except Exception as e:
            ocr = {"err": str(e)}

    cont = {}
    age = None
    if CONT.is_file():
        cont = json.loads(CONT.read_text(encoding="utf-8"))
        try:
            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(cont["at"].replace("Z", "+00:00"))
            ).total_seconds()
        except Exception:
            pass

    queue = []
    if QUEUE.is_file():
        queue = json.loads(QUEUE.read_text(encoding="utf-8")).get(
            "land_priority_queue", []
        )

    folders = []
    for item in sorted(queue, key=lambda x: -int(x.get("priority", 0))):
        if item.get("mode") == "catalog_only":
            folders.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "priority": item.get("priority"),
                    "mode": "catalog_only",
                    "pct": None,
                }
            )
            continue
        path = item.get("path") or ""
        if not Path(path).exists():
            folders.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "priority": item.get("priority"),
                    "mode": item.get("mode"),
                    "missing": True,
                }
            )
            continue
        st = folder_stats(con, path)
        st["id"] = item.get("id")
        st["label"] = item.get("label")
        st["priority"] = item.get("priority")
        st["mode"] = item.get("mode")
        folders.append(st)

    con.close()

    hist: list[dict] = []
    if OUT_HIST.is_file():
        for line in OUT_HIST.read_text(encoding="utf-8").splitlines()[-48:]:
            if line.strip():
                try:
                    hist.append(json.loads(line))
                except Exception:
                    pass

    sample = {
        "at": utc(),
        "registry": reg,
        "unique": uniq,
        "ocr_ok": ocr.get("ok_text", 0) if isinstance(ocr, dict) else 0,
    }
    thr = throughput(hist + [sample] if hist else [sample])

    # ETA: sum remaining high-priority full_land folders
    remaining = 0
    for f in folders:
        if f.get("mode") == "full_land" and f.get("disk_files") and f.get("registry") is not None:
            remaining += max(0, int(f["disk_files"]) - int(f["registry"]))
    fph = thr.get("files_per_hour") or 0
    eta_h = round(remaining / fph, 1) if fph and remaining else None

    res = vram_ram()
    chefs = chef_count()
    bottlenecks = []
    if chefs > 1:
        bottlenecks.append(f"MULTI_CHEF={chefs}")
    if chefs == 0:
        bottlenecks.append("NO_CHEF")
    if age is not None and age > 900:
        bottlenecks.append(f"STALE_STATE_age={int(age)}s")
    if res.get("ram_pct") and res["ram_pct"] >= 90:
        bottlenecks.append("HIGH_RAM")
    if not bottlenecks:
        bottlenecks.append("none")

    board = {
        "at": utc(),
        "memorycard": "100% COMPLETE",
        "registry": reg,
        "unique": uniq,
        "ocr": ocr,
        "process": proc,
        "continuous": {
            "cycle": cont.get("cycle"),
            "mode": (cont.get("assess") or {}).get("mode"),
            "limits": cont.get("limits"),
            "age_s": round(age, 1) if age is not None else None,
            "chef_processes": chefs,
        },
        "throughput": thr,
        "remaining_priority_files": remaining,
        "eta_hours_at_current_rate": eta_h,
        "resources": res,
        "bottlenecks": bottlenecks,
        "folders": folders,
        "build_s": round(time.time() - t0, 2),
    }

    OUT_JSON.write_text(json.dumps(board, indent=2), encoding="utf-8")
    with OUT_HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample) + "\n")

    # Barney MD
    lines = [
        f"# Silo Scoreboard v2 — {board['at'][:19]} UTC",
        "",
        "## Kitchen board (Barney)",
        f"- **MemoryCard:** {board['memorycard']}",
        f"- **Fridge size (registry):** {reg:,} · unique {uniq:,}",
        f"- **Chef:** {chefs} process · mode {(cont.get('assess') or {}).get('mode')} · age {board['continuous']['age_s']}s",
        f"- **OCR cooked:** ok_text={ocr.get('ok_text')} · still queued={ocr.get('queued')}",
        f"- **Throughput:** {thr.get('files_per_hour')} files/h · OCR {thr.get('ocr_per_hour')}/h",
        f"- **ETA (priority remaining):** {eta_h} hours" if eta_h else "- **ETA:** n/a (need more samples)",
        f"- **Bottlenecks:** {', '.join(bottlenecks)}",
        "",
        "## Priority folders",
        "| Priority | Folder | Land % | Disk files | Registry |",
        "|---------:|--------|-------:|-----------:|---------:|",
    ]
    for f in folders:
        if f.get("mode") == "catalog_only":
            lines.append(
                f"| {f.get('priority')} | {f.get('label')} | catalog | — | — |"
            )
        elif f.get("missing"):
            lines.append(
                f"| {f.get('priority')} | {f.get('label')} | missing | — | — |"
            )
        else:
            lines.append(
                f"| {f.get('priority')} | {f.get('label')} | {f.get('pct')}% | {f.get('disk_files')} | {f.get('registry')} |"
            )
    lines += [
        "",
        f"_Build {board['build_s']}s · JSON: `state/silo_scoreboard_v2.json`_",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: board[k] for k in ("registry", "unique", "throughput", "eta_hours_at_current_rate", "bottlenecks", "continuous")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
