#!/usr/bin/env python3
"""Autonomous OCR backlog worker — $0 Grok.

Industry pattern: land raw → parse → quality gate → reprocess queue → catalog.
Never blocks G→K drain. Prioritizes Navy/Medical PDFs; skips portraits.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
STATE = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
LOG = Path(r"D:\PhronesisVault\Operations\logs\silo-ocr-backlog-latest.md")
LADDER = Path(r"D:\HermesData\scripts\silo_robust_ocr_ladder.py")

PRIORITY_KEYS = (
    "order", "orders", "eval", "les", "certificate", "statement of service",
    "ncdoc", "elrod", "enterprise", "cvn", "sta-21", "boost", "nrotc",
    "accident", "mva", "crash", "cortisol", "gain entry", "reenlist",
    "separation", "oshanick", "nmcp", "vamc", "tricare", "dd214", "page 13",
)
MAX_OCR_ATTEMPTS = 4
# Gold medical/Navy (score>=500) gets extra retries — short-temp poppler + fat-promote
# were hanging the final tail when attempts hit 4 with chars still 0.
MAX_OCR_ATTEMPTS_GOLD = 12
# 2026-07-26: per-file hard cap so one fat PDF cannot hang the whole tick
# (Celery soft_time_limit pattern; OCRmyPDF batch isolation).
PER_FILE_TIMEOUT_S = 90
# Worker wall under orch 480s slot — exit clean with partial progress (Celery soft limit).
WORKER_WALL_S = 420
SKIP_RE = re.compile(r"(logo|icon|wallpaper|screenshot|_00\.jpg|cnsva\.jpg)", re.I)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}


def _process_one_timed(mod: Any, p: Path, tess: str, max_p: int, timeout_s: int = PER_FILE_TIMEOUT_S) -> dict:
    """Run ladder.process_one with a hard wall-clock cap (thread+join).

    On timeout: return status=error so queue advances attempts and tick continues.
    """
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["rec"] = mod.process_one(p, tess, True, max_p)
        except Exception as e:  # noqa: BLE001 — surface to caller path
            box["err"] = e

    t = threading.Thread(target=_target, name=f"ocr-one-{p.name[:24]}", daemon=True)
    t.start()
    t.join(timeout=max(15, int(timeout_s)))
    if t.is_alive():
        return {
            "status": "error",
            "chars": 0,
            "engine": f"timeout_{timeout_s}s",
            "quality": {"status": "error", "chars": 0},
            "error": f"per_file_timeout_{timeout_s}s",
        }
    if "err" in box:
        raise box["err"]
    return box.get("rec") or {"status": "error", "chars": 0, "engine": "empty_rec"}



def _dlq(path: str, err: str) -> None:
    try:
        from pathlib import Path as _P
        import json as _json
        from datetime import datetime, timezone

        dlq = _P(r"D:/HermesData/state/silo_dead_letter_queue.jsonl")
        rec = {
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": "ocr",
            "path": path,
            "error": str(err)[:400],
        }
        with dlq.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(rec) + "\n")
    except Exception:
        pass


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(STATE), timeout=120)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=120000")
    except Exception:
        pass
    con.execute(
        """CREATE TABLE IF NOT EXISTS ocr_queue (
            path TEXT PRIMARY KEY,
            score INTEGER,
            status TEXT,
            chars INTEGER,
            engine TEXT,
            updated_at TEXT,
            attempts INTEGER DEFAULT 0
        )"""
    )
    return con


try:
    from silo_relevance_heuristics import ocr_priority_boost, gold_score as _gold
except Exception:
    def ocr_priority_boost(path):
        return 0
    def _gold(path):
        return 50

def score(p: Path) -> int:
    low = str(p).lower()
    name = p.name.lower()
    s = 0
    if p.suffix.lower() == ".pdf":
        s += 50
    # Jeff 2026-07-13: medical imaging + DNA max priority
    if any(k in low for k in ("nmcp_imagery", "nmcp", "/medical", "medical", "dicom", ".dcm")):
        s += 80
    if any(k in low for k in ("mri", "ct scan", "ct_scan", "x-ray", "xray", "x_ray", "radiolog")):
        s += 60
    if any(k in low for k in ("dna", "genome", "23andme", "ancestry", "labcorp", "quest")):
        s += 55
    # 2026-07-26 SSOT park: neuroimaging / chrome / stock — not twin-OCR yield
    try:
        from ocr_park_patterns import is_ocr_park_path

        if is_ocr_park_path(p):
            s -= 250
    except Exception:
        if any(
            k in low
            for k in (
                "volbrain",
                "glass all lesion",
                "all lesion_jobs",
                "demo images",
                "depositphotos",
                "00-pics",
                "stock-photo",
            )
        ):
            s -= 250
    # Text-document boost (OCR actually works well here)
    if any(k in low for k in ("vamc meds", "myhealthevet", "prescription", "sf600", "sf-600", "progress note", "clinic note", "dd214", "navadmin", "buddy statement", "hp_scan")):
        s += 45
    if any(k in name for k in ("mri", "segmentation", "dicom")) and "note" not in name:
        s -= 15
    if p.suffix.lower() in {".dcm", ".nii", ".nrrd"}:
        s -= 50  # archive imaging — not OCR queue priority (2026-07-13)
    if "navy" in low or "medical" in low:
        s += 25
    for k in PRIORITY_KEYS:
        if k in name or k in low:
            s += 20
    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif"}:
        s -= 30
    if SKIP_RE.search(p.name):
        s -= 80
    ocr = Path(str(p) + ".ocr.md")
    if ocr.is_file():
        sz = ocr.stat().st_size
        if sz > 800:
            s -= 200  # done
        elif sz < 200:
            s += 40  # re-ocr thin
    if Path(str(p) + ".needs_ocr").is_file():
        s += 50
    try:
        s += ocr_priority_boost(p)
        if _gold(p) < 20:
            s -= 40
    except Exception:
        pass
    # Jeff 2026-07-13: prefer extractable PDFs over slow image tesseract for queue drain speed
    suf = p.suffix.lower()
    if suf == ".pdf":
        s += 25  # IMAGE_SLOW counterweight
    if suf in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}:
        s -= 15  # still process, but after PDFs
    return s


def discover(limit_scan: int = 8000) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    n = 0
    for root_name in ("Navy-Service", "Medical-Records", "Core-Personal"):
        root = SILO / root_name
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                continue
            if any(p.name.endswith(x) for x in (".ocr.md", ".train.md", ".context.json")):
                continue
            n += 1
            if n > limit_scan:
                break
            sc = score(p)
            if sc >= 40:
                found.append((sc, str(p)))
        if n > limit_scan:
            break
    found.sort(key=lambda x: -x[0])
    return found



def update_registry_process(path: str, status: str, chars: int) -> None:
    """Link OCR outcome into ingest_registry.process_status (depth + stop false requeue)."""
    reg = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
    if not reg.is_file():
        return
    try:
        con = sqlite3.connect(str(reg), timeout=60)
        row = con.execute(
            "SELECT id, process_status FROM ingest WHERE dest_path = ? LIMIT 1",
            (path,),
        ).fetchone()
        if not row:
            con.close()
            return
        # ok_text → extracted; terminal non-yield → catalog_only so gold_requeue
        # stops selecting ocr_queued/ocr_failed forever (2026-07-26 glass-lesion loop).
        new = None
        if status == "ok_text" and (chars or 0) > 80:
            new = "extracted"
        elif status in (
            "thin_image",
            "archive_skip",
            "corrupt_retired",
            "empty",
            "encrypted",
            "image_sparse",
            "missing",
        ):
            new = "catalog_only"
        if new and new != row[1]:
            con.execute(
                "UPDATE ingest SET process_status = ?, last_seen = ? WHERE id = ?",
                (new, utc(), row[0]),
            )
            con.commit()
        con.close()
    except Exception:
        pass


def load_ladder():
    spec = importlib.util.spec_from_file_location("ladder", LADDER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _terminalize_non_yield(con: sqlite3.Connection) -> int:
    """Bulk-close park/portrait/already-thin open rows (no OCR thrash).

    2026-07-26b autonomy: ocr_open was stuck ~40 on headshot JPGs with 1-20 chars
    re-entering needs_ocr every tick. Terminal thin_image + registry catalog_only.
    """
    try:
        from ocr_park_patterns import should_terminal_thin_image
    except Exception:
        return 0
    n = 0
    rows = list(
        con.execute(
            """SELECT path, chars, attempts, status FROM ocr_queue
               WHERE status IN ('queued','needs_ocr','error')"""
        )
    )
    now = utc()
    for path, chars, attempts, status in rows:
        if not should_terminal_thin_image(
            path, chars=chars, attempts=attempts, status=status
        ):
            # also: image with attempts>=1 and chars already known tiny
            suf = Path(path).suffix.lower()
            if suf not in IMAGE_EXTS:
                continue
            if int(attempts or 0) >= 1 and int(chars or 0) < 80:
                pass
            else:
                continue
        con.execute(
            """UPDATE ocr_queue SET status='thin_image', score=1,
               engine=COALESCE(NULLIF(engine,''),'thin_terminal_gate'),
               updated_at=? WHERE path=?""",
            (now, path),
        )
        update_registry_process(path, "thin_image", int(chars or 0))
        n += 1
    if n:
        con.commit()
    return n


def main() -> int:
    import argparse
    import time as _time

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--process-only", action="store_true", help="skip discover upsert (avoid lock storms)")
    ap.add_argument(
        "--wall-s",
        type=int,
        default=WORKER_WALL_S,
        help="soft wall seconds; exit 0 with partial progress (Celery soft_time_limit)",
    )
    args = ap.parse_args()
    t_wall0 = _time.time()

    con = db()
    open_q = con.execute(
        "SELECT COUNT(*) FROM ocr_queue WHERE status IN ('queued','needs_ocr','error')"
    ).fetchone()[0]
    # Streamline: skip expensive rglob discover when cook queue already deep
    if args.process_only:
        found = []
    elif open_q > 150 and not args.discover_only:
        found = []
        print(json.dumps({"discover_skipped": True, "open_queue": open_q}))
    else:
        found = discover()
    for sc, path in found[:2000]:
        con.execute(
            """INSERT INTO ocr_queue(path, score, status, chars, engine, updated_at, attempts)
               VALUES(?,?, 'queued', NULL, NULL, ?, 0)
               ON CONFLICT(path) DO UPDATE SET score=excluded.score""",
            (path, sc, utc()),
        )
    con.commit()

    # Autonomy gate: close non-yield open rows before spending tesseract budget
    terminalized = _terminalize_non_yield(con)

    queued = con.execute(
        "SELECT COUNT(*) FROM ocr_queue WHERE status IN ('queued','needs_ocr','error')"
    ).fetchone()[0]
    done = con.execute("SELECT COUNT(*) FROM ocr_queue WHERE status='ok_text'").fetchone()[0]

    if args.discover_only:
        print(
            json.dumps(
                {
                    "queued": queued,
                    "done": done,
                    "discovered": len(found),
                    "terminalized": terminalized,
                }
            )
        )
        return 0

    mod = load_ladder()
    tess = mod.tesseract_bin()
    # Gold (score>=500) may exceed attempts=4 after path/paren poppler fails;
    # still reselect until MAX_OCR_ATTEMPTS_GOLD so final DD2807/2808 tail drains.
    # PDF-first: image thrash must not starve real multipage docs (2026-07-26b).
    rows = con.execute(
        f"""SELECT path, score FROM ocr_queue
           WHERE status IN ('queued','needs_ocr','error') AND score >= 40
             AND (
               attempts < {MAX_OCR_ATTEMPTS}
               OR (score >= 500 AND attempts < {MAX_OCR_ATTEMPTS_GOLD})
             )
           ORDER BY CASE
                      WHEN lower(path) LIKE '%%.pdf' THEN 0
                      ELSE 1
                    END,
                    CASE status WHEN 'queued' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                    score DESC, attempts ASC LIMIT ?""",
        (args.limit,),
    ).fetchall()

    results = []
    wall_hit = False
    for path, sc in rows:
        if (_time.time() - t_wall0) >= max(30, int(args.wall_s)):
            wall_hit = True
            results.append(
                {
                    "path": "_wall",
                    "status": "wall_stop",
                    "error": f"worker_wall_{args.wall_s}s",
                }
            )
            break
        p = Path(path)
        if not p.is_file():
            con.execute(
                "UPDATE ocr_queue SET status='missing', updated_at=? WHERE path=?",
                (utc(), path),
            )
            continue
        # Pre-OCR park/portrait gate (no tesseract burn).
        # IMPORTANT: do not force attempts=1 into should_terminal_thin_image —
        # that would retire never-tried document scans.
        try:
            from ocr_park_patterns import should_terminal_thin_image, is_ocr_park_path

            pre_att = con.execute(
                "SELECT attempts, chars FROM ocr_queue WHERE path=?", (path,)
            ).fetchone()
            att0 = int((pre_att or (0, 0))[0] or 0)
            ch0 = (pre_att or (0, None))[1]
            gate = is_ocr_park_path(p) or should_terminal_thin_image(
                p, chars=ch0, attempts=att0, status="queued"
            )
            if gate:
                con.execute(
                    """UPDATE ocr_queue SET status='thin_image', score=1,
                       engine='park_or_portrait_gate', updated_at=?, attempts=attempts+1
                       WHERE path=?""",
                    (utc(), path),
                )
                update_registry_process(path, "thin_image", int(ch0 or 0))
                con.commit()
                results.append(
                    {
                        "path": p.name,
                        "status": "thin_image",
                        "chars": int(ch0 or 0),
                        "engine": "park_or_portrait_gate",
                    }
                )
                continue
        except Exception:
            pass
        try:
            # Medical/Navy scans: more pages; cheap first for others
            max_p = 12 if any(k in str(p).lower() for k in ('medical', 'navy', 'nmcp', 'vamc')) else 6
            # Wall-clock isolation — hang on one PDF must not kill the tick
            rec = _process_one_timed(mod, p, tess, max_p, PER_FILE_TIMEOUT_S)
            if rec.get("error") == f"per_file_timeout_{PER_FILE_TIMEOUT_S}s":
                con.execute(
                    """UPDATE ocr_queue SET status='error', engine=?, updated_at=?, attempts=attempts+1
                       WHERE path=?""",
                    (rec.get("engine") or "timeout", utc(), path),
                )
                att = con.execute(
                    "SELECT attempts FROM ocr_queue WHERE path=?", (path,)
                ).fetchone()
                max_att = MAX_OCR_ATTEMPTS_GOLD if (sc or 0) >= 500 else MAX_OCR_ATTEMPTS
                if att and att[0] >= max_att:
                    con.execute(
                        "UPDATE ocr_queue SET status='corrupt_retired', updated_at=? WHERE path=?",
                        (utc(), path),
                    )
                    _dlq(path, f"max_attempts:per_file_timeout")
                con.commit()
                results.append(
                    {
                        "path": p.name,
                        "status": "error",
                        "chars": 0,
                        "engine": rec.get("engine"),
                        "error": "per_file_timeout",
                    }
                )
                continue
            q = rec.get("quality") or {}
            if isinstance(q, str):
                try:
                    q = json.loads(q.replace("'", '"'))
                except Exception:
                    q = {}
            status = q.get("status") or rec.get("status") or "unknown"
            chars = q.get("chars") or rec.get("chars") or 0
            engine = rec.get("engine") or ""
            twin = q.get("twin_useful") or rec.get("twin_useful")
            if twin and status != "ok_text":
                status = "ok_text"
            # Swiss-watch: fat extracts are twin-usable even if ladder said needs_ocr
            try:
                if int(chars or 0) >= 800 and status in ("needs_ocr", "unknown", "thin", "empty"):
                    status = "ok_text"
            except Exception:
                pass
            # Terminal thin-image gate after attempt (stop needs_ocr thrash)
            try:
                from ocr_park_patterns import should_terminal_thin_image

                if status in ("needs_ocr", "unknown", "thin", "empty") and should_terminal_thin_image(
                    p, chars=int(chars or 0), attempts=1, status=status
                ):
                    status = "thin_image"
                    engine = (engine or "") + "+thin_gate"
            except Exception:
                if (
                    p.suffix.lower() in IMAGE_EXTS
                    and status in ("needs_ocr", "unknown", "thin")
                    and int(chars or 0) < 80
                ):
                    status = "thin_image"
            con.execute(
                """UPDATE ocr_queue SET status=?, chars=?, engine=?, updated_at=?, attempts=attempts+1
                   WHERE path=?""",
                (status, int(chars or 0), engine, utc(), path),
            )
            update_registry_process(path, status, int(chars or 0))
            results.append({"path": p.name, "status": status, "chars": chars, "engine": engine})
            con.commit()  # per-file
        except Exception as e:
            try:
                con.execute(
                    """UPDATE ocr_queue SET status='error', updated_at=?, attempts=attempts+1 WHERE path=?""",
                    (utc(), path),
                )
                att = con.execute(
                    "SELECT attempts FROM ocr_queue WHERE path=?", (path,)
                ).fetchone()
                max_att = MAX_OCR_ATTEMPTS_GOLD if (sc or 0) >= 500 else MAX_OCR_ATTEMPTS
                if att and att[0] >= max_att:
                    con.execute(
                        "UPDATE ocr_queue SET status='corrupt_retired', updated_at=? WHERE path=?",
                        (utc(), path),
                    )
                    _dlq(path, f"max_attempts:{e}")
                con.commit()  # per-file
            except Exception:
                pass
            results.append({"path": p.name, "status": "error", "error": str(e)[:160]})
    try:
        con.commit()
    except Exception:
        pass

    queued2 = con.execute(
        "SELECT COUNT(*) FROM ocr_queue WHERE status IN ('queued','needs_ocr','error')"
    ).fetchone()[0]
    done2 = con.execute("SELECT COUNT(*) FROM ocr_queue WHERE status='ok_text'").fetchone()[0]
    con.close()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# OCR backlog worker — {utc()}",
        "",
        f"processed **{len(results)}** · queue remaining **{queued2}** · ok_text **{done2}** · terminalized_pre **{terminalized}**",
        f"wall_hit={wall_hit} wall_s={args.wall_s}",
        "",
    ]
    for r in results:
        lines.append(f"- {r.get('status')} chars={r.get('chars')} `{r.get('path')}` {r.get('error','')}")
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "processed": len(results),
                "queue_remaining": queued2,
                "ok_text_total": done2,
                "terminalized_pre": terminalized,
                "wall_hit": wall_hit,
                "results": results[:12],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
