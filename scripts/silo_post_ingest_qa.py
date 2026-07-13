#!/usr/bin/env python3
"""Post-ingestion QA scoreboard for K: silo kitchen (Medical/Navy first).

Inventory: integrity (fixity), OCR depth, process_status, zero-byte, missing dest.
Optional: run fixity sample, requeue thin OCR, kick OCR tranche.

Usage:
  python silo_post_ingest_qa.py
  python silo_post_ingest_qa.py --fix-fixity 40 --run-ocr 15
  python silo_post_ingest_qa.py --requeue-thin
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
OCR_DB = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\silo-post-ingest-qa-latest.md")
STATE = Path(r"D:\HermesData\state\silo_post_ingest_qa.json")
SCRIPTS = Path(r"D:\HermesData\scripts")

DOMAINS = {
    "Medical-Records": "Medical-Records",
    "Navy-Service": "Navy-Service",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_stats(con: sqlite3.Connection, like: str) -> Dict[str, Any]:
    total = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE domain LIKE ?", (f"%{like}%",)
    ).fetchone()[0]
    by_ps = dict(
        con.execute(
            "SELECT process_status, COUNT(*) FROM ingest WHERE domain LIKE ? GROUP BY process_status",
            (f"%{like}%",),
        ).fetchall()
    )
    fixity = dict(
        con.execute(
            "SELECT COALESCE(CAST(fixity_ok AS TEXT),'null'), COUNT(*) FROM ingest WHERE domain LIKE ? GROUP BY fixity_ok",
            (f"%{like}%",),
        ).fetchall()
    )
    zero = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE domain LIKE ? AND IFNULL(size,0)=0",
        (f"%{like}%",),
    ).fetchone()[0]
    no_sha = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE domain LIKE ? AND (sha256 IS NULL OR sha256='')",
        (f"%{like}%",),
    ).fetchone()[0]
    processed = sum(
        by_ps.get(k, 0) for k in ("extracted", "context_enriched", "derivative_ok")
    )
    depth_pct = round(100 * processed / total, 1) if total else 0.0
    return {
        "total": total,
        "process_status": by_ps,
        "fixity": fixity,
        "zero_byte": zero,
        "no_sha": no_sha,
        "depth_processed": processed,
        "depth_pct": depth_pct,
        "unprocessed": by_ps.get("unprocessed", 0),
    }


def ocr_stats() -> Dict[str, Any]:
    if not OCR_DB.exists():
        return {"error": "no ocr db"}
    con = sqlite3.connect(str(OCR_DB), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    by = dict(con.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status").fetchall())
    thin = con.execute(
        "SELECT COUNT(*) FROM ocr_queue WHERE status='ok_text' AND IFNULL(chars,0) < 200"
    ).fetchone()[0]
    needs = con.execute(
        "SELECT COUNT(*) FROM ocr_queue WHERE status IN ('queued','needs_ocr','error')"
    ).fetchone()[0]
    ok = by.get("ok_text", 0)
    con.close()
    return {"by_status": by, "queue_open": needs, "ok_text": ok, "thin_ok_text": thin}


def sample_sidecars(domain_folder: str, limit: int = 2500) -> Dict[str, int]:
    root = SILO / domain_folder
    out = {"media_files": 0, "ocr_md": 0, "thin_ocr": 0, "train_md": 0, "missing_dest_checked": 0}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            continue
        if any(p.name.endswith(x) for x in (".ocr.md", ".train.md", ".meta.json")):
            continue
        out["media_files"] += 1
        ocr = Path(str(p) + ".ocr.md")
        if ocr.is_file():
            out["ocr_md"] += 1
            try:
                if len(ocr.read_text(encoding="utf-8", errors="replace").strip()) < 80:
                    out["thin_ocr"] += 1
            except Exception:
                out["thin_ocr"] += 1
        if Path(str(p) + ".train.md").is_file():
            out["train_md"] += 1
        if out["media_files"] >= limit:
            break
    return out


def requeue_thin(limit: int = 200) -> int:
    if not OCR_DB.exists():
        return 0
    con = sqlite3.connect(str(OCR_DB), timeout=60)
    con.execute('PRAGMA busy_timeout=60000')
    rows = con.execute(
        """SELECT path FROM ocr_queue
           WHERE (status='ok_text' AND IFNULL(chars,0) < 200)
              OR status='needs_ocr'
           ORDER BY score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    n = 0
    for (path,) in rows:
        con.execute(
            "UPDATE ocr_queue SET status='queued', updated_at=? WHERE path=?",
            (utc(), path),
        )
        n += 1
    con.commit()
    con.close()
    return n


def missing_dest_sample(con: sqlite3.Connection, like: str, limit: int = 30) -> List[str]:
    missing = []
    for (path,) in con.execute(
        "SELECT dest_path FROM ingest WHERE domain LIKE ? AND dest_path IS NOT NULL LIMIT 5000",
        (f"%{like}%",),
    ):
        if not path:
            continue
        if not Path(path).exists():
            missing.append(path)
            if len(missing) >= limit:
                break
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-fixity", type=int, default=0, help="run registry_fixity_batch limit")
    ap.add_argument("--run-ocr", type=int, default=0, help="run ocr_backlog_worker limit")
    ap.add_argument("--requeue-thin", action="store_true")
    ap.add_argument("--sidecar-limit", type=int, default=2500)
    args = ap.parse_args()

    report: Dict[str, Any] = {"at": utc(), "domains": {}, "actions": {}}

    con = sqlite3.connect(str(REG))
    overall = {
        "registry_total": con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0],
        "process_status": dict(
            con.execute("SELECT process_status, COUNT(*) FROM ingest GROUP BY process_status")
        ),
    }
    report["overall"] = overall

    for key, folder in DOMAINS.items():
        st = domain_stats(con, key if key != "Medical-Records" else "Medical")
        if key == "Navy-Service":
            st = domain_stats(con, "Navy")
        st["sidecars"] = sample_sidecars(folder, args.sidecar_limit)
        st["missing_dest_sample"] = missing_dest_sample(
            con, "Medical" if "Medical" in key else "Navy", 15
        )
        st["missing_dest_sample_n"] = len(st["missing_dest_sample"])
        report["domains"][key] = st
    con.close()

    report["ocr"] = ocr_stats()

    if args.requeue_thin:
        report["actions"]["requeued_thin"] = requeue_thin(250)

    if args.fix_fixity > 0:
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "registry_fixity_batch.py"),
                "--limit",
                str(args.fix_fixity),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        report["actions"]["fixity"] = {
            "exit": r.returncode,
            "out_tail": (r.stdout or r.stderr or "")[-600:],
        }

    if args.run_ocr > 0:
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "silo_ocr_backlog_worker.py"),
                "--limit",
                str(args.run_ocr),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        report["actions"]["ocr"] = {
            "exit": r.returncode,
            "out_tail": (r.stdout or r.stderr or "")[-800:],
        }

    # scoreboard markdown
    med = report["domains"].get("Medical-Records", {})
    navy = report["domains"].get("Navy-Service", {})
    ocr = report["ocr"]
    lines = [
        f"# Post-ingest QA (Kitchen) — {report['at']}",
        "",
        "**Lane:** land done → cook (fixity · OCR · clean text · train)",
        "",
        "## Scoreboard",
        "",
        f"| Shelf | Landed | Depth % | Unprocessed | Zero-byte | Fixity OK/FAIL/null | OCR sidecars (sample) | Thin OCR |",
        f"|-------|-------:|--------:|------------:|----------:|---------------------|----------------------:|---------:|",
    ]
    for name, st in (("Medical", med), ("Navy", navy)):
        fx = st.get("fixity") or {}
        sc = st.get("sidecars") or {}
        lines.append(
            f"| {name} | {st.get('total')} | {st.get('depth_pct')}% | {st.get('unprocessed')} | "
            f"{st.get('zero_byte')} | {fx.get('1',0)}/{fx.get('0',0)}/{fx.get('null',0)} | "
            f"{sc.get('ocr_md',0)}/{sc.get('media_files',0)} | {sc.get('thin_ocr',0)} |"
        )
    lines += [
        "",
        f"**OCR queue:** open **{ocr.get('queue_open')}** · ok_text **{ocr.get('ok_text')}** · thin ok **{ocr.get('thin_ok_text')}**",
        f"**Registry total:** {overall['registry_total']}",
        "",
        "## Issues (inventory)",
        "",
    ]
    issues = []
    for name, st in (("Medical", med), ("Navy", navy)):
        if st.get("zero_byte"):
            issues.append(f"- {name}: **{st['zero_byte']}** zero-byte files (repair/re-pull candidates)")
        if st.get("missing_dest_sample_n"):
            issues.append(
                f"- {name}: **{st['missing_dest_sample_n']}+** missing dest paths (sample logged in JSON)"
            )
        sc = st.get("sidecars") or {}
        if sc.get("media_files") and sc.get("ocr_md", 0) / max(sc["media_files"], 1) < 0.2:
            issues.append(
                f"- {name}: OCR coverage low on sample ({sc.get('ocr_md')}/{sc.get('media_files')}) — backlog cooking"
            )
        if st.get("depth_pct", 0) < 20:
            issues.append(f"- {name}: depth {st.get('depth_pct')}% — extract/enrich lag (expected while land >> depth)")
    if not issues:
        issues.append("- No critical integrity reds on sample.")
    lines.extend(issues)
    lines += [
        "",
        "## Plan (incremental)",
        "",
        "1. Fixity wave on Medical/Navy unset rows",
        "2. OCR backlog worker priority Medical/Navy (already scored)",
        "3. Requeue thin OCR (<200 chars) for re-ladder",
        "4. Text clean + medical_navy_text_index on new .ocr.md",
        "5. Zero-byte / fixity_ok=0 → re-pull from G: when source online",
        "",
        "[[Operations/Post-Ingest-QA-Repair-Enrichment-CANONICAL-2026-07-13]]",
        "",
    ]
    if report.get("actions"):
        lines += ["## Actions this run", "", f"```json\n{json.dumps(report['actions'], indent=2)[:2000]}\n```", ""]

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    STATE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "state": str(STATE), "summary": {
        "medical_depth_pct": med.get("depth_pct"),
        "navy_depth_pct": navy.get("depth_pct"),
        "ocr_queue_open": ocr.get("queue_open"),
        "ocr_ok_text": ocr.get("ok_text"),
        "actions": list(report.get("actions") or {}),
    }}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
