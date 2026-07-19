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

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

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
try:
    from drain_dlq import record as dlq_record
except Exception:
    def dlq_record(source, dest, error):
        pass
try:
    from modality_detect import detect as modality_detect
except Exception:
    def modality_detect(path):
        return "unknown"

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
K_SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
STAGING = K_SILO / "_Staging-From-G-Drive"
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-drain-receipt-latest.md")
RECEIPT_DRY = Path(r"D:\PhronesisVault\Operations\logs\g-to-k-drain-receipt-dry-run-latest.md")
# Resume cursor so skip-heavy trees don't re-walk from root every wave.
# Research: rsync batch/continuation; S3 ListObjects continuation-token;
# fscrawler/checkpointed FS crawls; queue-first bounded scan (silo canon).
WALK_CURSOR = Path(r"D:\HermesData\state\g_to_k_walk_cursor.json")

# Domain routing SSOT (expanded after MemoryCard trial lessons)
try:
    from domain_route import domain_for as _domain_for
except Exception:
    def _domain_for(name: str, path_hint: str = "") -> str:
        return "Core-Personal/_Inbox"


try:
    from silo_relevance_heuristics import land_decision, is_junk_path, gold_score
except Exception:
    def land_decision(path):
        return "land"
    def is_junk_path(path):
        return False
    def gold_score(path):
        return 50

def domain_for(name: str, path_hint: str = "") -> str:
    """Strip routing noise; preserve real filename on disk separately."""
    return _domain_for((name or "").strip(), path_hint)


def copy_file(src: Path, dest: Path) -> str:
    """Efficient copy: robocopy for multi-MB files, buffered shutil otherwise.

    Returns method tag: robocopy|shutil_buf|shutil
    Full-tree robocopy is intentionally NOT used — we must classify per file.
    """
    import subprocess
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    # robocopy: large files on Windows (unbuffered I/O)
    if size >= 2 * 1024 * 1024:  # 2 MB+
        cmd = [
            "robocopy",
            str(src.parent),
            str(dest.parent),
            src.name,
            "/J",  # unbuffered
            "/R:1",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NC",
            "/NS",
            "/NP",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode < 8 and dest.exists() and dest.stat().st_size == size:
            return "robocopy"
    # buffered binary copy for medium/small (faster than tiny default)
    if size >= 64 * 1024:
        with src.open("rb") as rf, dest.open("wb") as wf:
            shutil.copyfileobj(rf, wf, length=8 * 1024 * 1024)
        try:
            shutil.copystat(src, dest)
        except Exception:
            pass
        return "shutil_buf"
    shutil.copy2(src, dest)
    return "shutil"


def _path_keys(s: str) -> list[str]:
    s = str(s)
    return list({s, s.replace("/", "\\"), s.replace("\\", "/")})


def sha256_file(path: Path, limit: int = 32 * 1024 * 1024) -> str:
    """Content fingerprint. Large files (>20MB) use size+mtime+head for speed
    (Booksbloom ebooks) — still unique enough for land dedupe; fidelity rehash later.
    """
    try:
        st = path.stat()
        size = st.st_size
        mtime = int(st.st_mtime)
    except OSError:
        size, mtime = 0, 0
    # Fast path for large media/ebooks
    if size > 20 * 1024 * 1024:
        h = hashlib.sha256()
        h.update(f"FAST|{size}|{mtime}|".encode())
        try:
            with path.open("rb") as f:
                h.update(f.read(4 * 1024 * 1024))
        except OSError:
            pass
        h.update(b"|FAST_HASH")
        return h.hexdigest()
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


def load_walk_cursor() -> dict:
    if WALK_CURSOR.is_file():
        try:
            return json.loads(WALK_CURSOR.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_walk_cursor(data: dict) -> None:
    WALK_CURSOR.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data or {})
    data["updated"] = datetime.now(timezone.utc).isoformat()
    if atomic_write_json is not None:
        atomic_write_json(WALK_CURSOR, data, indent=2)
    else:
        WALK_CURSOR.write_text(json.dumps(data, indent=2), encoding="utf-8")


def iter_candidates(
    root: Path,
    limit: int,
    skip_sources: set[str] | None = None,
    skip_hashes: set[str] | None = None,
    max_scan: int = 2_000_000,
    start_after: str | None = None,
) -> tuple[list[Path], dict]:
    """Return up to `limit` *new* candidates (skips known sources).

    2026-07-19 harden (skip-heavy Google_Backups / takeout veins):
    - known skip_sources do NOT burn max_scan budget (only walk_cap bounds full walk)
    - optional start_after resume cursor so waves advance past already-drained prefixes
    - one automatic wrap if cursor leaves no candidates (tree may have new files earlier)

    Walks until `limit` new files found, max_scan *new* files examined, or walk_cap.
    """
    out: list[Path] = []
    stats = {
        "walked_files": 0,
        "skipped_known": 0,
        "new_examined": 0,
        "emitted": 0,
        "last_path": None,
        "start_after": start_after,
        "wrapped": False,
        "hit_walk_cap": False,
        "hit_max_scan": False,
    }
    if not root.exists():
        return out, stats
    skip_sources = skip_sources or set()
    # Allow walking well past a large already-landed prefix (66k+ GB registry).
    walk_cap = max(int(max_scan) * 4, int(max_scan) + 80_000, 120_000)

    def _known(sp: str) -> bool:
        sp_win = sp.replace("/", "\\")
        sp_nix = sp.replace("\\", "/")
        return sp in skip_sources or sp_win in skip_sources or sp_nix in skip_sources

    def _walk_once(resume_after: str | None, allow_wrap_marker: bool) -> None:
        past = resume_after is None
        resume_keys = set(_path_keys(resume_after)) if resume_after else set()
        for p in root.rglob("*"):
            if stats["walked_files"] >= walk_cap:
                stats["hit_walk_cap"] = True
                break
            if not p.is_file():
                continue
            try:
                _dec = land_decision(p)
                if _dec == "skip":
                    continue
                if _dec == "catalog":
                    continue  # full land skip; catalog job separate
            except Exception:
                pass
            if p.name.startswith(".") or p.name.endswith(".meta.json"):
                continue
            if p.name.lower() in {"desktop.ini", "thumbs.db", "thumbs.db:encryptable"}:
                continue
            if p.suffix.lower() in {".tmp", ".crdownload", ".partial", ".jsonlz4", ".final"}:
                continue
            # Holistic nutrition: skip OS/app junk even inside personal trees (Booksbloom Carbonite dumps)
            _low = str(p).lower().replace(chr(92), "/")
            if any(
                junk in _low
                for junk in (
                    "/appdata/",
                    "/application data/",
                    "/local settings/",
                    "carbonite restored",
                    "/diagnostics/",
                    "/temp/",
                    "/tmp/",
                    "/cache/",
                    "/caches/",
                    "/node_modules/",
                    "/.git/",
                    "/__pycache__/",
                    "/windows/system32",
                    "/program files",
                    "$recycle.bin",
                    "system volume information",
                    "thumbs.db",
                    "/inetcache/",
                    "/packages/",
                    "/microsoft/windows/",
                    "old firefox data",
                    "/firefox/",
                    ".jsonlz4",
                )
            ):
                continue

            # Jeff 2026-07-13: catalog-only music — skip bulk audio land
            if p.suffix.lower() in {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wma"}:
                continue
            sp_n = str(p).lower().replace("\\", "/")
            if any(
                m in sp_n
                for m in (
                    "/old_music/",
                    "/music rip/",
                    "z_jenni_kids_music",
                    "/virtualbox vms/",
                    "/hyper-v/",
                    "/vmware/",
                )
            ):
                continue
            try:
                # Jeff 2026-07-13: game ISOs / disk images / huge archives = catalog-only, not land
                if p.suffix.lower() in {
                    ".iso",
                    ".vmdk",
                    ".vdi",
                    ".vhd",
                    ".vhdx",
                    ".qcow2",
                    ".ova",
                    ".img",
                    ".nrg",
                    ".mds",
                    ".mdf",
                    ".cue",
                    ".bin",
                }:
                    continue
                if p.suffix.lower() in {".7z", ".zip", ".rar"}:
                    sz = p.stat().st_size
                    low = (p.name + " " + str(p)).lower()
                    gold = any(
                        k in low
                        for k in (
                            "medical",
                            "navy",
                            "nmcp",
                            "records",
                            "orders",
                            "eval",
                            "legal",
                            "bcnr",
                            "nvlsp",
                            "export",
                            "takeout",
                            "mail",
                            "dna",
                            "genome",
                            "journal",
                            "bloom",
                            "personal",
                            "va ",
                            "tax",
                            "scan",
                        )
                    )
                    # Jeff 2026-07-13: evaluate zips — keep gold/content archives; skip bulk junk
                    if sz > 500_000_000 and not gold:
                        continue
                    if sz > 50_000_000 and not gold:
                        # still skip large non-gold blobs (likely media/vm packs)
                        if any(
                            k in low
                            for k in (
                                "virtualbox",
                                "vmdk",
                                "vdi",
                                "iso",
                                "game",
                                "steam",
                                "music",
                                "mp3",
                            )
                        ):
                            continue
                        if sz > 150_000_000:
                            continue
            except Exception:
                continue

            sp = str(p)
            stats["last_path"] = sp
            stats["walked_files"] += 1

            # Resume: skip until we pass the cursor path (exclusive).
            if not past:
                if sp in resume_keys or sp.replace("/", "\\") in resume_keys or sp.replace("\\", "/") in resume_keys:
                    past = True
                continue

            if _known(sp):
                stats["skipped_known"] += 1
                continue

            # New candidate (not yet in skip_sources)
            stats["new_examined"] += 1
            if stats["new_examined"] > max_scan:
                stats["hit_max_scan"] = True
                break
            out.append(p)
            stats["emitted"] = len(out)
            if len(out) >= limit:
                break

        if allow_wrap_marker and resume_after and not out and past:
            stats["wrapped"] = True

    _walk_once(start_after, allow_wrap_marker=True)
    # If cursor left us with nothing (past end, or cursor path missing), wrap once from root.
    if not out and start_after:
        stats["walked_files"] = 0
        stats["skipped_known"] = 0
        stats["new_examined"] = 0
        stats["hit_walk_cap"] = False
        stats["hit_max_scan"] = False
        stats["wrap_pass"] = True
        stats["wrapped"] = True
        _walk_once(None, allow_wrap_marker=False)
    return out, stats



def load_priority_sources():
    """Config-driven land order; skip catalog_only and ~complete folders."""
    import json
    import sqlite3
    from pathlib import Path as _P

    qpath = _P(r"D:/HermesData/config/land_priority_queue.json")
    if not qpath.is_file():
        return []
    try:
        data = json.loads(qpath.read_text(encoding="utf-8"))
        items = data.get("land_priority_queue") or []
        items = sorted(items, key=lambda x: -int(x.get("priority") or 0))
        reg = _P(r"D:/HermesData/state/ingest_registry.sqlite3")
        con = None
        if reg.is_file():
            try:
                con = sqlite3.connect(str(reg), timeout=30)
                con.execute("PRAGMA busy_timeout=30000")
            except Exception:
                con = None
        out = []
        for it in items:
            if it.get("mode") in ("catalog_only", "never", "land_complete"):
                continue
            path = it.get("path")
            if not path:
                continue
            root = _P(path)
            if not root.exists():
                continue
            # skip nearly complete folders so chef advances to next priority
            if con is not None:
                try:
                    root_n = str(root).replace("/", "\\").rstrip("\\")
                    reg_n = con.execute(
                        "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?",
                        (root_n + "\\" + "%",),
                    ).fetchone()[0]
                    # light disk sample cap (was 120k — hung weekly smoke / drain planning)
                    disk_n = 0
                    for i, fp in enumerate(root.rglob("*")):
                        if fp.is_file():
                            disk_n += 1
                        if i > 8000:
                            break
                    # Only treat as complete when sample is dense AND registry is large
                    if disk_n >= 200 and reg_n >= disk_n and reg_n / max(disk_n, 1) >= 0.995:
                        continue
                except Exception:
                    pass
            out.append(root)
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
        return out
    except Exception:
        return []



def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            k.CloseHandle(h)
            return True
        return False
    except Exception:
        try:
            import os

            os.kill(int(pid), 0)
            return True
        except Exception:
            return False


def _count_live_drains() -> list[int]:
    """PIDs whose command line is g_to_k_safe_drain.py (exclude self)."""
    import os
    import subprocess as _sp

    me = os.getpid()
    pids: list[int] = []
    try:
        r = _sp.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { "
                "$_.Name -like 'python*' -and $_.CommandLine -like '*g_to_k_safe_drain.py*' } "
                "| Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                p = int(line)
                if p != me:
                    pids.append(p)
    except Exception:
        pass
    return pids


def acquire_single_writer_lock() -> tuple[bool, str]:
    """Singleton land writer for apply mode — SQLite registry is one-writer.

    Research: sqlite.org/wal.html — WAL allows concurrent readers but still
    one writer; dual drain = lock storms / stalled ticks / corrupt risk.
    """
    import atexit
    import os

    lock = Path(r"D:\HermesData\state\g_to_k_safe_drain.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    others = _count_live_drains()
    if others:
        return False, f"live_drain_pids={others}"
    if lock.is_file():
        try:
            old = int((lock.read_text(encoding="utf-8").strip().split() or ["0"])[0])
        except Exception:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            return False, f"lock_held_by_pid={old}"
    payload = f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n"
    if atomic_write_text is not None:
        atomic_write_text(lock, payload if payload.endswith("\n") else payload + "\n", min_bytes=1)
    else:
        lock.write_text(payload, encoding="utf-8")

    def _release() -> None:
        try:
            if lock.is_file():
                cur = lock.read_text(encoding="utf-8")
                if cur.startswith(str(os.getpid())):
                    lock.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_release)
    return True, f"acquired pid={os.getpid()}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually copy (default dry-run)")
    ap.add_argument("--ai-inbox", action="store_true", help="Local AI domain vote for _Inbox names (capped)")
    ap.add_argument("--ai-inbox-cap", type=int, default=8, help="Max local AI domain calls per wave")
    ap.add_argument("--limit", type=int, default=40, help="Max files this wave")
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source root (repeatable). Defaults to MemoryCard GD + live My Drive",
    )
    args = ap.parse_args()
    # Single-writer gate (apply only). Dry-run may still run for planning probes.
    if args.apply:
        ok_lock, lock_msg = acquire_single_writer_lock()
        if not ok_lock:
            print(json.dumps({"status": "skip_single_writer", "reason": lock_msg}, indent=2))
            return 0  # soft skip — not an error; chef/continuous continues
    # Default: MemoryCard first; full-throttle adds C2 personal G: trees
    default_sources = load_priority_sources() or [
        Path(r"G:/MemoryCard_Backups/Google Drive(archive)"),
        Path(r"G:/MemoryCard_Backups/Google Drive"),
    ]
    ft = Path(r"D:/HermesData/state/silo_full_throttle.json")
    if ft.is_file():
        try:
            import json as _json
            if _json.loads(ft.read_text(encoding="utf-8")).get("enabled"):
                for extra in (
                    "G:/NMCP_Imagery_Export",
                    "G:/Alex",
                    "G:/Booksbloom",
                    
                    
                    
                    "G:/OneDrive",
                    "G:/Downloads",
                    "G:/Spencer",
                    "G:/SEC501_Restore",
                    "G:/FileHistory",
                    "G:/Head Start",
                ):
                    ep = Path(extra)
                    if ep.is_dir():
                        default_sources.append(ep)
        except Exception:
            pass
    sources = [Path(s) for s in args.source] or default_sources

    # Known sources from ingest registry → skip early (wave efficiency)
    # Scope skip load to active source roots (huge speed win on Booksbloom mid-tree)
    skip_sources: set[str] = set()
    icon_pre = ingest_connect() if ingest_connect else None
    if icon_pre is not None:
        try:
            if sources:
                clauses = []
                params: list[str] = []
                for s in sources:
                    root_n = str(s).replace("/", "\\").rstrip("\\")
                    clauses.append("source_path LIKE ?")
                    params.append(root_n + "\\%")
                    clauses.append("source_path LIKE ?")
                    params.append(str(s).replace("\\", "/").rstrip("/") + "/%")
                sql = (
                    "SELECT source_path FROM ingest WHERE status IN "
                    "('copied','verified','processed') AND ("
                    + " OR ".join(clauses)
                    + ")"
                )
                rows = icon_pre.execute(sql, params).fetchall()
            else:
                rows = icon_pre.execute(
                    "SELECT source_path FROM ingest WHERE status IN ('copied','verified','processed')"
                ).fetchall()
            for r in rows:
                sp = r[0] if not hasattr(r, "keys") else r["source_path"]
                if not sp:
                    continue
                for k in _path_keys(sp):
                    skip_sources.add(k)
        except Exception:
                pass

    # In-memory hash set — O(1) dupe checks (archive overlaps live heavily)
    known_hashes: set[str] = set()
    if icon_pre is not None:
        try:
            for (h,) in icon_pre.execute(
                "SELECT sha256 FROM hash_seen WHERE sha256 IS NOT NULL AND sha256!=''"
            ):
                known_hashes.add(h)
            for (h,) in icon_pre.execute(
                "SELECT DISTINCT sha256 FROM ingest WHERE sha256 IS NOT NULL AND sha256!=''"
            ):
                known_hashes.add(h)
        except Exception:
            pass

    def safe_name(name: str, max_len: int = 120) -> str:
        bad = '<>:"|?*'
        for ch in bad:
            name = name.replace(ch, "_")
        name = name.strip(" .")
        if len(name) > max_len:
            stem, dot, ext = name.rpartition(".")
            if dot and len(ext) <= 12:
                name = stem[: max_len - len(ext) - 1] + "." + ext
            else:
                name = name[:max_len]
        return name or "file"

    def unique_dest(src: Path, src_root: Path, dom: str) -> Path:
        """Avoid false skip-exists when same filename already on K from another source."""
        try:
            rel = src.relative_to(src_root)
        except Exception:
            rel = Path(src.name)
        # sanitize each part
        parts = [safe_name(part, 80) for part in rel.parts[:-1]] + [safe_name(rel.name, 120)]
        rel = Path(*parts) if parts else Path(safe_name(src.name))
        base = K_SILO / dom / "from-g-drive" / rel
        if not base.exists():
            return base
        digest = __import__("hashlib").sha256(str(src).encode("utf-8", errors="replace")).hexdigest()[:8]
        return base.with_name(safe_name(f"{base.stem}__{digest}{base.suffix}", 120))

    planned = []
    walk_stats_by_root: dict[str, dict] = {}
    cursor_state = load_walk_cursor()
    ai_used = 0
    # Oversample candidates: archive has many content-dupes of live GD.
    # Plan more than limit so apply can fill real copies after hash skips.
    # Bound hard — scanning millions of already-ingested paths hung weekly smoke (180s+).
    plan_cap = min(max(args.limit * 8, args.limit + 40), max(args.limit * 20, 400))
    for src_root in sources:
        if len(planned) >= plan_cap:
            break
        need = plan_cap - len(planned)
        # Candidate pool + max_scan proportional to need (not 20k–2M unbounded walks)
        pool_limit = min(max(need * 12, args.limit * 20), 4000)
        # new_examined budget (skip_sources no longer burns this)
        scan_budget = min(max(pool_limit * 40, 2000), 80_000)
        root_key = str(src_root).replace("/", "\\").rstrip("\\")
        start_after = None
        try:
            ent = (cursor_state.get("roots") or {}).get(root_key) or {}
            start_after = ent.get("last_path") or None
        except Exception:
            start_after = None
        pool, wstats = iter_candidates(
            src_root,
            pool_limit,
            skip_sources=skip_sources,
            max_scan=scan_budget,
            start_after=start_after,
        )
        walk_stats_by_root[root_key] = wstats
        for f in pool:
            dom = domain_for(f.name)
            if args.ai_inbox and dom.endswith("_Inbox") and ai_used < args.ai_inbox_cap:
                try:
                    from domain_ai_assist import assess as ai_assess
                    ar = ai_assess(f.name, use_ai=True)
                    if ar.get("final") and not str(ar.get("final")).endswith("_Inbox"):
                        dom = ar["final"]
                    ai_used += 1
                except Exception:
                    pass
            dest = unique_dest(f, src_root, dom)
            planned.append((f, dest, dom, str(src_root)))
            if len(planned) >= plan_cap:
                break

    # Class filter: 2 always; class 3 hybrid OK for approved G: personal campaigns
    # (touch_policy defaults unknown→3 — was blocking C2 NMCP/Alex/music entirely).
    # Still skip class 1 and relevance noise. Never Hermes/Vault/OS.
    NEVER_ROOTS = (
        r"D:/HermesData",
        r"D:/PhronesisVault",
        r"D:/ComfyUI",
        r"C:/Windows",
        r"C:/Program Files",
        r"G:/Program Files",
    )
    filtered = []
    for src, dest, dom, root in planned:
        sp = str(src)
        if any(sp.startswith(n) or n.lower() in sp.lower() for n in NEVER_ROOTS):
            continue
        cls, note = touch_classify(src)
        if cls == 1:
            continue
        if cls not in (2, 3):
            continue
        # class 3 only from G: personal (or explicit USB later)
        if cls == 3 and not (sp.startswith("G:\\") or sp.startswith("G:/")):
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
        if args.apply and copied >= args.limit:
            break
        status = "planned"
        # Registry / filesystem guards against re-processing
        if dest.exists():
            status = "skip-exists"
            skipped += 1
            # Lesson 2026-07-12: dest already on K but source not in registry
            # → endless re-plans. Register alias so skip_sources works next wave.
            if args.apply and icon is not None and ingest_register:
                try:
                    digest = sha256_file(src) if src.is_file() else ""
                    ingest_register(
                        icon, str(src), str(dest), digest=digest or None,
                        size=src.stat().st_size if src.is_file() else 0,
                        domain=dom, status="copied",
                    )
                    icon.commit()
                    if digest:
                        known_hashes.add(digest)
                except Exception:
                    pass
            try:
                from silo_multi_provenance import merge_meta
                merge_meta(dest, src, domain=dom)
            except Exception:
                pass
        elif icon is not None and already_ingested_source and already_ingested_source(icon, str(src)):
            status = "skip-registry-source"
            skipped += 1
        elif args.apply:
            try:
                digest = sha256_file(src)
                if digest in known_hashes or (
                    icon is not None and already_have_hash and already_have_hash(icon, digest)
                ):
                    status = "skip-registry-hash"
                    skipped += 1
                    known_hashes.add(digest)
                    # Register source alias so next waves don't re-plan same bytes
                    if ingest_register:
                        try:
                            ingest_register(
                                icon, str(src), str(dest), digest=digest,
                                size=src.stat().st_size, domain=dom, status="copied",
                            )
                            icon.commit()
                        except Exception:
                            pass
                    try:
                        from silo_multi_provenance import merge_meta
                        merge_meta(dest, src, digest=digest, domain=dom)
                    except Exception:
                        pass
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
                    known_hashes.add(digest)
            except Exception as e:
                status = f"ERR {e}"
                try:
                    dlq_record(str(src), str(dest), str(e))
                except Exception:
                    pass
        elif not args.apply and icon is not None and already_ingested_source and already_ingested_source(icon, str(src)):
            status = "would-skip-registry"
            skipped += 1
        lines.append(f"| `{src.name[:60]}` | {dom} | `{dest}` | {status} |")

    if args.apply and meta_batch:
        STAGING.mkdir(parents=True, exist_ok=True)
        batch_path = STAGING / f"batch-{TS}.json"
        if atomic_write_json is not None:
            atomic_write_json(batch_path, meta_batch, indent=2)
        else:
            batch_path.write_text(json.dumps(meta_batch, indent=2), encoding="utf-8")

    lines += [
        "",
        f"**Copied:** {copied} · **Skipped:** {skipped} · **Planned rows:** {len(planned)}",
        "",
        "## Walk stats",
    ]
    for rk, ws in (walk_stats_by_root or {}).items():
        lines.append(
            f"- `{rk}`: walked={ws.get('walked_files')} known_skip={ws.get('skipped_known')} "
            f"new={ws.get('new_examined')} emitted={ws.get('emitted')} "
            f"wrap={ws.get('wrap_pass') or ws.get('wrapped')} "
            f"cursor_in={(ws.get('start_after') or '')[-80:]}"
        )
    lines += [
        "",
        "## Guardrails",
        "- Copy only — sources untouched",
        "- No Drive purge in this script",
        "- Broad domains only (open taxonomy)",
        "- Full drain needs many waves + Jeff green light before any purge",
        "- 2026-07-19: walk resume cursor + skip_sources no longer burn max_scan",
        "",
        "[[Operations/G-to-K-Drain-Assurance-2026-07-10]]",
        "",
    ]
    # Advance resume cursor only on apply waves (real progress).
    if args.apply:
        roots_cur = dict((cursor_state.get("roots") or {}))
        for rk, ws in (walk_stats_by_root or {}).items():
            lp = ws.get("last_path")
            if not lp:
                continue
            # If we wrapped and still empty productive, reset cursor for that root.
            if ws.get("wrap_pass") and int(ws.get("emitted") or 0) == 0:
                roots_cur[rk] = {
                    "last_path": None,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "reset": "empty_after_wrap",
                }
            else:
                roots_cur[rk] = {
                    "last_path": lp,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "walked_files": ws.get("walked_files"),
                    "skipped_known": ws.get("skipped_known"),
                    "emitted": ws.get("emitted"),
                    "copied_wave": copied,
                    "skipped_wave": skipped,
                }
        cursor_state["roots"] = roots_cur
        try:
            save_walk_cursor(cursor_state)
        except Exception:
            pass

    receipt_path = RECEIPT if args.apply else RECEIPT_DRY
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_text is not None:
        atomic_write_text(receipt_path, "\n".join(lines), min_bytes=20)
    else:
        receipt_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "planned": len(planned),
                "copied": copied,
                "skipped": skipped,
                "receipt": str(receipt_path),
                "walk_stats": walk_stats_by_root,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
