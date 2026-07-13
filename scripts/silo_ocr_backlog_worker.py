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
from datetime import datetime, timezone
from pathlib import Path

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
SKIP_RE = re.compile(r"(logo|icon|wallpaper|screenshot|_00\.jpg|cnsva\.jpg)", re.I)



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
    # Text-document boost (OCR actually works well here)
    if any(k in low for k in ("vamc meds", "myhealthevet", "prescription", "sf600", "sf-600", "progress note", "clinic note", "dd214", "navadmin", "buddy statement", "hp_scan")):
        s += 45
    if any(k in name for k in ("mri", "segmentation", "dicom")) and "note" not in name:
        s -= 15
    if p.suffix.lower() in {".dcm", ".nii", ".nrrd"}:
        s += 70
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
    """Link OCR success into ingest_registry.process_status (lessons: depth must show in catalog)."""
    reg = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
    if not reg.is_file():
        return
    try:
        con = sqlite3.connect(str(reg))
        # match dest_path or source basename
        row = con.execute(
            "SELECT id, process_status FROM ingest WHERE dest_path = ? LIMIT 1",
            (path,),
        ).fetchone()
        if not row:
            con.close()
            return
        new = "extracted" if status == "ok_text" and (chars or 0) > 80 else row[1]
        if status == "ok_text" and (chars or 0) > 80:
            con.execute(
                "UPDATE ingest SET process_status = ?, last_seen = ? WHERE id = ?",
                ("extracted", utc(), row[0]),
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


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--process-only", action="store_true", help="skip discover upsert (avoid lock storms)")
    args = ap.parse_args()

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

    queued = con.execute(
        "SELECT COUNT(*) FROM ocr_queue WHERE status IN ('queued','needs_ocr','error')"
    ).fetchone()[0]
    done = con.execute("SELECT COUNT(*) FROM ocr_queue WHERE status='ok_text'").fetchone()[0]

    if args.discover_only:
        print(json.dumps({"queued": queued, "done": done, "discovered": len(found)}))
        return 0

    mod = load_ladder()
    tess = mod.tesseract_bin()
    rows = con.execute(
        """SELECT path, score FROM ocr_queue
           WHERE status IN ('queued','needs_ocr','error') AND score >= 40 AND attempts < 4
           ORDER BY CASE status WHEN 'queued' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                    score DESC, attempts ASC LIMIT ?""",
        (args.limit,),
    ).fetchall()

    results = []
    for path, sc in rows:
        p = Path(path)
        if not p.is_file():
            con.execute(
                "UPDATE ocr_queue SET status='missing', updated_at=? WHERE path=?",
                (utc(), path),
            )
            continue
        try:
            # Medical/Navy scans: more pages; cheap first for others
            max_p = 12 if any(k in str(p).lower() for k in ('medical', 'navy', 'nmcp', 'vamc')) else 6
            rec = mod.process_one(p, tess, True, max_p)
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
                if att and att[0] >= MAX_OCR_ATTEMPTS:
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
        f"processed **{len(results)}** · queue remaining **{queued2}** · ok_text **{done2}**",
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
                "results": results[:12],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
