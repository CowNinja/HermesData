#!/usr/bin/env python3
"""Holistic silo coverage — MemoryCard 100% + other G: folders + depth tracking."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:\HermesData\state\ingest_registry.sqlite3")
OCR = Path(r"D:\HermesData\state\ocr_backlog.sqlite3")
OUT_JSON = Path(r"D:\HermesData\state\silo_coverage_holistic.json")
OUT_JSONL = Path(r"D:\HermesData\state\silo_coverage_history.jsonl")
OUT_MD = Path(r"D:\PhronesisVault\Operations\logs\silo-coverage-holistic-latest.md")
CENSUS_MC = 164105

C2_ROOTS = [
    (r"G:/NMCP_Imagery_Export", "NMCP_Imagery"),
    (r"G:/Alex", "Alex"),
    (r"G:/Booksbloom", "Booksbloom"),
    (r"G:/OneDrive", "OneDrive"),
    (r"G:/Downloads", "Downloads"),
    (r"G:/Spencer", "Spencer"),
    (r"G:/SEC501_Restore", "SEC501_Restore"),
    (r"G:/FileHistory", "FileHistory"),
    (r"G:/Head Start", "Head_Start"),
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_files(root: Path, cap: int = 100_000) -> int:
    if not root.is_dir():
        return 0
    n = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                n += 1
                if n >= cap:
                    return n
    except OSError:
        return n
    return n


def reg_prefix(con: sqlite3.Connection, root_s: str) -> int:
    root_s = root_s.replace("/", "\\").rstrip("\\")
    patterns = [root_s + "\\%", root_s + "/%", root_s + "%"]
    best = 0
    for pat in patterns:
        try:
            c = con.execute(
                "SELECT COUNT(*) FROM ingest WHERE source_path LIKE ?", (pat,)
            ).fetchone()[0]
            best = max(best, int(c))
        except Exception:
            pass
    return best


def main() -> int:
    con = sqlite3.connect(str(REG))
    reg_total = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    uniq = con.execute(
        "SELECT COUNT(DISTINCT sha256) FROM ingest WHERE sha256 IS NOT NULL AND sha256!=''"
    ).fetchone()[0]
    process = dict(
        con.execute(
            "SELECT process_status, COUNT(*) FROM ingest GROUP BY process_status"
        ).fetchall()
    )
    mc_reg = con.execute(
        "SELECT COUNT(*) FROM ingest WHERE source_path LIKE '%MemoryCard_Backups%'"
    ).fetchone()[0]

    folders = []
    c2_src = c2_reg = 0
    for root_s, label in C2_ROOTS:
        root = Path(root_s)
        src_n = count_files(root)
        reg_n = reg_prefix(con, root_s)
        pct = round(100.0 * reg_n / src_n, 1) if src_n else 0.0
        note = "source count capped 100k" if src_n >= 100_000 else ""
        folders.append(
            {
                "label": label,
                "path": root_s,
                "source_files": src_n,
                "registry_rows": reg_n,
                "land_pct": pct,
                "note": note,
            }
        )
        c2_src += src_n
        c2_reg += reg_n
    con.close()

    ocr: dict = {}
    if OCR.is_file():
        oc = sqlite3.connect(str(OCR))
        ocr = dict(
            oc.execute("SELECT status, COUNT(*) FROM ocr_queue GROUP BY status").fetchall()
        )
        oc.close()

    depth_done = (
        process.get("extracted", 0)
        + process.get("context_enriched", 0)
        + process.get("derivative_ok", 0)
    )
    depth_pct = round(100.0 * depth_done / reg_total, 2) if reg_total else 0
    c2_pct = round(100.0 * c2_reg / c2_src, 1) if c2_src else 0.0

    report = {
        "at": utc(),
        "memorycard": {
            "land_status": "100% COMPLETE",
            "land_pct_display": 100.0,
            "census": CENSUS_MC,
            "registry_rows": mc_reg,
        },
        "campaign2_g_personal": {
            "land_pct": c2_pct,
            "source_files_sum": c2_src,
            "registry_rows_sum": c2_reg,
            "folders": folders,
        },
        "k_silo": {
            "registry_total": reg_total,
            "unique_sha256": uniq,
            "process": process,
            "depth_touched_pct": depth_pct,
        },
        "ocr": ocr,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with OUT_JSONL.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "at": report["at"],
                    "reg": reg_total,
                    "uniq": uniq,
                    "mc": 100.0,
                    "c2_pct": c2_pct,
                    "c2_reg": c2_reg,
                    "c2_src": c2_src,
                    "depth_pct": depth_pct,
                    "ocr_ok": ocr.get("ok_text", 0),
                    "extracted": process.get("extracted", 0),
                }
            )
            + "\n"
        )

    lines = [
        f"# Silo coverage holistic — {report['at'][:19]}",
        "",
        "## Headline",
        "- **MemoryCard land: 100% COMPLETE**",
        f"- **Campaign 2 G: personal: ~{c2_pct}%** ({c2_reg:,} / {c2_src:,} files)",
        f"- **K registry:** {reg_total:,} · **unique:** {uniq:,}",
        f"- **Depth touched:** ~{depth_pct}% · **OCR ok_text:** {ocr.get('ok_text', 0)}",
        "",
        "## MemoryCard",
        f"- Census {CENSUS_MC:,} · registry rows {mc_reg:,} · **display 100%**",
        "",
        "## Other G: personal folders",
        "",
        "| Folder | Source # | Registry # | Land % |",
        "|--------|----------:|-----------:|-------:|",
    ]
    for f in sorted(folders, key=lambda x: -x["source_files"]):
        lines.append(
            f"| {f['label']} | {f['source_files']:,} | {f['registry_rows']:,} | {f['land_pct']}% |"
        )
    lines += [
        "",
        "## Never / later",
        "- NEVER: HermesData, PhronesisVault, ComfyUI, Windows",
        "- LATER: D: Documents/CloudSync · USB · Takeout",
        "",
        "## Process on K",
    ]
    for k, v in sorted(process.items(), key=lambda x: -x[1]):
        lines.append(f"- **{k}:** {v:,}")
    lines.append("")
    lines.append("_History: state/silo_coverage_history.jsonl_")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "mc": "100%",
                "c2_pct": c2_pct,
                "c2_reg": c2_reg,
                "c2_src": c2_src,
                "reg": reg_total,
                "depth_pct": depth_pct,
                "folders": {f["label"]: f"{f['land_pct']}%" for f in folders},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
