#!/usr/bin/env python3
"""Mark process_status on registry rows from sidecar presence.

Statuses:
  unprocessed | extracted | context_enriched | ocr_queued | derivative_ok
  | ghost_cleared | catalog_only

2026-07-26: honor .ocr.md / .stt.md twins; mark missing dest as ghost_cleared
so unprocessed counters and html_thin pick stop thrashing missing Takeout paths.
2026-08-01: .needs_ocr.json; catalog_only exts; --unprocessed-only fast path
(closes residual extract loop without full-table thrash).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
OUT = Path(r"D:\HermesData\state\process_status_batch_latest.json")

# Non-content / pointer / junk -> catalog_only (no OCR/STT thrash)
CATALOG_EXT = {
    ".gdoc",
    ".gsheet",
    ".gslides",
    ".gdraw",
    ".gform",
    ".gtable",
    ".url",
    ".lnk",
    ".bak",
    ".tmp",
    ".temp",
    ".part",
    ".crdownload",
    ".ds_store",
    ".db-journal",
    ".db-wal",
    ".db-shm",
    ".lcp",
    ".dcp",
    ".apk",
    ".so",
    ".dll",
    ".exe",
    ".class",
    ".pyc",
    ".pyo",
    ".o",
    ".a",
    ".lib",
    ".pdb",
    ".ilk",
    ".svg",  # vector asset; catalog unless gold later
    ".ico",
    ".cur",
    ".dat",
    ".properties",
    ".css",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".softbank_392",
}

NATIVE_TEXT = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".eml",
    ".rtf",
    ".xml",
    ".log",
    ".yaml",
    ".yml",
    ".vcf",
    ".ics",
    ".ini",
    ".cfg",
    ".conf",
}

# Images default catalog_only unless gold path (OCR gated elsewhere)
IMAGE_EXT = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".heif",
}

GOLD_HINTS = (
    "medical-records",
    "navy-service",
    "diagnosis",
    "orders",
    "awards",
    "passport",
    "visa",
    "tax",
    "irs",
)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_gold(path: str) -> bool:
    low = (path or "").lower().replace("/", "\\")
    return any(h in low for h in GOLD_HINTS)


def infer_status(p: Path, cur: str | None) -> str:
    """Infer process_status from path + sidecars. Prefer stronger statuses."""
    if not p.is_file():
        return "ghost_cleared"

    suf = p.suffix.lower()
    train = Path(str(p) + ".train.md")
    stt = Path(str(p) + ".stt.md")
    ocr = Path(str(p) + ".ocr.md")
    ctx_train = Path(str(p) + ".context.train.md")
    needs = Path(str(p) + ".needs_ocr")
    needs_json = Path(str(p) + ".needs_ocr.json")
    meta = Path(str(p) + ".meta.json")
    ctx = Path(str(p) + ".context.json")
    extract_txt = Path(str(p) + ".extract.txt")
    extract_json = Path(str(p) + ".extract.json")
    pdf_txt = Path(str(p) + ".txt")
    office_md = Path(str(p) + ".office.md")
    office_json = Path(str(p) + ".office.json")
    html_md = Path(str(p) + ".html.md")
    email_md = Path(str(p) + ".email.md")
    AUDIO_EXT = {
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".wma",
        ".amr",
        ".3gp",
        ".webm",
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".m4v",
    }

    # Strongest first
    try:
        if (
            (train.is_file() and train.stat().st_size >= 40)
            or (ctx_train.is_file() and ctx_train.stat().st_size >= 40)
            or (stt.is_file() and stt.stat().st_size >= 40)
        ):
            return "derivative_ok"
        if office_md.is_file() and office_md.stat().st_size >= 40:
            return "derivative_ok"
        # silo_office_extract writes .office.json (not always .office.md)
        if office_json.is_file() and office_json.stat().st_size >= 20:
            try:
                import json as _json

                oj = _json.loads(
                    office_json.read_text(encoding="utf-8", errors="replace")
                )
                if isinstance(oj, dict):
                    text = oj.get("text") or oj.get("body") or ""
                    chars = int(oj.get("chars") or oj.get("text_len") or len(str(text)))
                    ok_flag = oj.get("ok")
                    if ok_flag is False:
                        pass  # fall through
                    elif chars >= 40 or (ok_flag is True and chars >= 1):
                        return "derivative_ok"
                    elif ok_flag is True:
                        return "extracted"
            except Exception:
                return "extracted"
        if html_md.is_file() and html_md.stat().st_size >= 40:
            return "derivative_ok"
        if email_md.is_file() and email_md.stat().st_size >= 40:
            return "derivative_ok"
    except OSError:
        pass

    if ctx.is_file():
        return "context_enriched"

    try:
        if ocr.is_file() and ocr.stat().st_size >= 40:
            return "extracted"
        if extract_txt.is_file() and extract_txt.stat().st_size >= 40:
            return "extracted"
        # pdf sidecar text written next to file
        if suf == ".pdf" and pdf_txt.is_file() and pdf_txt.stat().st_size >= 40:
            return "extracted"
        # OCR ladder / residual extract.json
        if extract_json.is_file() and extract_json.stat().st_size >= 20:
            try:
                import json as _json

                ej = _json.loads(
                    extract_json.read_text(encoding="utf-8", errors="replace")
                )
                q = (ej.get("quality") or {}) if isinstance(ej, dict) else {}
                if (
                    q.get("twin_useful")
                    or q.get("status") == "ok_text"
                    or int(q.get("chars") or 0) >= 80
                ):
                    return "derivative_ok"
                if q.get("status") in ("needs_ocr", "thin", "empty"):
                    return "ocr_queued"
                return "extracted"
            except Exception:
                return "extracted"
    except OSError:
        pass

    if needs.is_file() or needs_json.is_file():
        return "ocr_queued"

    # meta-only after extract attempt without text -> still ocr_queued if pdf/image
    if meta.is_file() and suf in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        # if meta says needs ocr / empty text, queue; else leave
        try:
            raw = meta.read_text(encoding="utf-8", errors="replace")[:2000]
            if "needs_ocr" in raw.lower() or '"chars": 0' in raw or '"text_len": 0' in raw:
                return "ocr_queued"
        except OSError:
            pass

    # Audio without STT twin belongs on stt lane, not eternal unprocessed
    if suf in AUDIO_EXT:
        return "stt_queued"

    # Tiny office stubs are catalog noise
    try:
        if suf in {".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx", ".rtf", ".csv"}:
            if p.stat().st_size < 200:
                return "catalog_only"
    except OSError:
        pass

    if suf in CATALOG_EXT:
        return "catalog_only"

    if suf in IMAGE_EXT:
        # gold images stay unprocessed for OCR gold path; others catalog
        if is_gold(str(p)):
            return cur if cur in ("ocr_queued", "extracted", "derivative_ok") else "unprocessed"
        return "catalog_only"

    if suf in NATIVE_TEXT:
        try:
            if p.stat().st_size > 0:
                return "extracted"
        except OSError:
            return "ghost_cleared"

    # no extension Google pointers often end with space + nothing useful
    if suf == "" or suf == ".":
        name = p.name.lower()
        if name.endswith(".gdoc") or "navadmin" in name:
            return "catalog_only"

    return cur or "unprocessed"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument(
        "--unprocessed-only",
        action="store_true",
        help="Only scan unprocessed/NULL rows (residual close-loop)",
    )
    ap.add_argument(
        "--prefer-twins",
        action="store_true",
        help="Bias gold silo roots first for twin promote",
    )
    ap.add_argument(
        "--catalog-other",
        action="store_true",
        help="Aggressively mark CATALOG_EXT + non-gold images as catalog_only",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not DB.is_file():
        print(json.dumps({"ok": False, "error": "no db"}))
        return 2

    con = sqlite3.connect(str(DB), timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute("PRAGMA table_info(ingest)").fetchall()]
    if "process_status" not in cols:
        try:
            con.execute(
                "ALTER TABLE ingest ADD COLUMN process_status TEXT DEFAULT 'unprocessed'"
            )
            con.commit()
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"alter fail {e}"}))
            return 2

    where = "WHERE dest_path IS NOT NULL"
    if args.unprocessed_only:
        where += " AND (process_status IS NULL OR process_status='unprocessed')"

    order = """ORDER BY CASE WHEN process_status IS NULL OR process_status='unprocessed' THEN 0 ELSE 1 END"""
    if args.prefer_twins:
        order = """ORDER BY
          CASE
            WHEN lower(dest_path) LIKE '%medical-records%' THEN 0
            WHEN lower(dest_path) LIKE '%navy-service%' THEN 1
            WHEN lower(dest_path) LIKE '%core-personal%' THEN 2
            WHEN lower(dest_path) LIKE '%finance%' THEN 3
            ELSE 8
          END,
          CASE WHEN process_status IS NULL OR process_status='unprocessed' THEN 0 ELSE 1 END
        """

    pull = max(args.limit * 8, args.limit + 50)
    rows = con.execute(
        f"""SELECT rowid AS rid, dest_path, process_status FROM ingest
           {where}
           {order}
           LIMIT ?""",
        (pull,),
    ).fetchall()

    updated = 0
    scanned = 0
    ghosts = 0
    derivatives = 0
    cataloged = 0
    ocr_q = 0
    extracted_n = 0
    by_new: dict[str, int] = {}
    samples: list[dict] = []

    for r in rows:
        dest = r["dest_path"]
        if not dest:
            continue
        p = Path(dest)
        rid = r["rid"]
        cur = r["process_status"]
        scanned += 1

        status = infer_status(p, cur)
        # catalog-other mode: force catalog on matching unprocessed
        if args.catalog_other and (cur is None or cur == "unprocessed"):
            suf = p.suffix.lower()
            if suf in CATALOG_EXT or (suf in IMAGE_EXT and not is_gold(dest)):
                status = "catalog_only"

        if status != (cur or "unprocessed") and status != cur:
            # don't downgrade strong statuses accidentally
            rank = {
                "derivative_ok": 50,
                "context_enriched": 40,
                "extracted": 30,
                "ocr_queued": 20,
                "stt_queued": 20,
                "catalog_only": 15,
                "ghost_cleared": 10,
                "unprocessed": 0,
                None: 0,
            }
            if rank.get(status, 0) < rank.get(cur, 0) and cur not in (
                None,
                "unprocessed",
                "",
            ):
                continue
            if not args.dry_run:
                con.execute(
                    "UPDATE ingest SET process_status=?, last_seen=? WHERE rowid=?",
                    (status, utc(), rid),
                )
            updated += 1
            by_new[status] = by_new.get(status, 0) + 1
            if status == "ghost_cleared":
                ghosts += 1
            elif status == "derivative_ok":
                derivatives += 1
            elif status == "catalog_only":
                cataloged += 1
            elif status == "ocr_queued":
                ocr_q += 1
            elif status == "extracted":
                extracted_n += 1
            if len(samples) < 12:
                samples.append({"dest": dest[:120], "from": cur, "to": status})

        if updated >= args.limit:
            break

    if not args.dry_run:
        con.commit()

    try:
        counts = con.execute(
            "SELECT process_status, COUNT(*) c FROM ingest GROUP BY process_status"
        ).fetchall()
        by = {row[0]: row[1] for row in counts}
    except Exception:
        by = {}
    unprocessed = int(by.get("unprocessed") or 0) + int(by.get(None) or 0)
    con.close()

    rep = {
        "ts": utc(),
        "ok": True,
        "scanned": scanned,
        "updated": updated,
        "ghosts": ghosts,
        "derivatives": derivatives,
        "cataloged": cataloged,
        "ocr_queued": ocr_q,
        "extracted": extracted_n,
        "by_new": by_new,
        "unprocessed_now": unprocessed,
        "by_process": by,
        "unprocessed_only": bool(args.unprocessed_only),
        "dry_run": bool(args.dry_run),
        "samples": samples,
    }
    try:
        OUT.write_text(json.dumps(rep, indent=2) + "\n", encoding="ascii")
    except Exception:
        pass
    print(json.dumps(rep, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
