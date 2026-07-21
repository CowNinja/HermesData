#!/usr/bin/env python3
"""BooksBloom / Jan Library golden eval — regression pack (no Grok).

Research basis (2026-07-19 overnight):
- RAG evals should separate retrieval hit-rate from answer faithfulness
  (Braintrust / RAGAS-style: context precision/recall + faithfulness).
- Keyword/source expectations beat free-form grading for small private corpora.
- Fail closed on empty retrieve; never invent expected authors/ISBNs.

Usage:
  python jan_golden_eval.py              # retrieve-only (fast)
  python jan_golden_eval.py --llm        # also call talk_to_jan path
  python jan_golden_eval.py --k 8
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
OUT_JSON = Path(r"D:\PhronesisVault\Operations\logs\jan-golden-eval-latest.json")
OUT_MD = Path(r"D:\PhronesisVault\Operations\logs\jan-golden-eval-latest.md")

sys.path.insert(0, str(SCRIPTS))
from jan_author_chunk_index import retrieve  # noqa: E402
try:
    from atomic_io import atomic_write_json, atomic_write_text  # noqa: E402
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

# Each case: question, expected phrases in retrieved text OR answer, optional must_lane
CASES: list[dict] = [
    {
        "id": "wswtr_title",
        "q": "What is Who Should We Then Read about?",
        "expect_any": ["who should we then", "living books", "authors", "read"],
        "prefer_lanes": ["jan_shelf", "booksbloom_gold", "public"],
    },
    {
        "id": "living_books",
        "q": "What does Jan say about living books versus textbooks?",
        "expect_any": ["living", "textbook", "author", "voice", "books"],
        "prefer_lanes": ["jan_shelf", "booksbloom_gold", "workshop_catalog"],
    },
    {
        "id": "keepers",
        "q": "What is Keepers of the Books about?",
        "expect_any": ["keepers", "home library", "library"],
        "prefer_lanes": ["booksbloom_gold", "workshop_catalog", "jan_shelf"],
    },
    {
        "id": "cradle_to_grade",
        "q": "What is the Cradle to Grade workshop?",
        "expect_any": ["cradle to grade", "cradle", "reading path", "ages"],
        "prefer_lanes": ["workshop_catalog", "public", "booksbloom_gold"],
    },
    {
        "id": "foundational_five",
        "q": "What is The Foundational Five?",
        "expect_any": ["foundational five", "foundation", "home library"],
        "prefer_lanes": ["workshop_catalog", "public", "booksbloom_gold"],
    },
    {
        "id": "mighty_whitey",
        "q": "What is Mighty Whitey in Jan's writing?",
        "expect_any": ["mighty whitey", "van", "white"],
        "prefer_lanes": ["jan_shelf", "booksbloom_gold", "family_living"],
    },
    {
        "id": "hi_ho_silver",
        "q": "What is the current BooksBloom van called?",
        "expect_any": ["hi-ho silver", "hi ho silver", "2015", "express"],
        "prefer_lanes": ["family_living", "public"],
    },
    {
        "id": "soil_preparers",
        "q": "What ministry verse or image do Gary and Jan use for BooksBloom?",
        "expect_any": ["matthew", "soil", "13:23", "prepar"],
        "prefer_lanes": ["public", "booksbloom_gold", "jan_shelf"],
    },
    {
        "id": "homeschool_start",
        "q": "When did Jan and Gary begin homeschooling their children?",
        "expect_any": ["1982", "homeschool"],
        "prefer_lanes": ["public", "workshop_catalog", "booksbloom_gold"],
    },
    {
        "id": "conference_2026",
        "q": "Which 2026 conferences is BooksBloom planning to attend?",
        "expect_any": ["greenville", "cincinnati", "orlando", "round rock", "fpea", "ghc"],
        "prefer_lanes": ["convention_master", "public"],
    },
    {
        "id": "wswtr_author_count_public",
        "q": "How many authors does the public site say are in Who Should We Then Read volume 1?",
        "expect_any": ["157", "authors"],
        "prefer_lanes": ["public"],
    },
    {
        "id": "business_by_books",
        "q": "What is Business by the Books?",
        "expect_any": ["business by the books", "business", "bookselling", "ministry"],
        "prefer_lanes": ["workshop_catalog", "booksbloom_gold"],
    },
    # Extended 2026-07-21 cook — still corpus-only expectations
    {
        "id": "yee_haw_boys",
        "q": "What is the Yee Haw Books for Boys workshop about?",
        "expect_any": ["yee haw", "boys", "adventure", "heroic"],
        "prefer_lanes": ["workshop_catalog", "booksbloom_gold"],
    },
    {
        "id": "wswtr_edition_2001",
        "q": "What does the gold WSWTR text say about the 2001 revised edition?",
        "expect_any": ["2001", "revised", "152", "expanded"],
        "prefer_lanes": ["author_list", "booksbloom_gold", "jan_shelf"],
    },
    {
        "id": "author_list_partial",
        "q": "Which authors appear on the gold WSWTR author list extract?",
        "expect_any": ["author", "alcott", "alger", "partial", "edition"],
        "prefer_lanes": ["author_list", "booksbloom_gold"],
    },
    {
        "id": "convention_niche_2019",
        "q": "Where was the 2019 NICHE Homeschool Iowa BooksBloom speaking engagement?",
        "expect_any": ["des moines", "niche", "iowa", "valley", "2019"],
        "prefer_lanes": ["convention_master", "booksbloom_gold"],
    },
]


def _blob(hits: list[dict]) -> str:
    return " ".join((h.get("text") or "") for h in hits).lower()


def _has_any(text: str, needles: list[str]) -> list[str]:
    hit = []
    for n in needles:
        if n.lower() in text:
            hit.append(n)
    return hit


def eval_retrieve(k: int) -> list[dict]:
    rows = []
    for case in CASES:
        hits = retrieve(case["q"], k=k)
        blob = _blob(hits)
        matched = _has_any(blob, case["expect_any"])
        lanes = [h.get("lane") for h in hits]
        prefer = set(case.get("prefer_lanes") or [])
        lane_ok = (not prefer) or any(l in prefer for l in lanes)
        ok = bool(hits) and bool(matched)
        rows.append(
            {
                "id": case["id"],
                "q": case["q"],
                "ok": ok,
                "lane_ok": lane_ok,
                "matched_keywords": matched,
                "hit_count": len(hits),
                "lanes": lanes,
                "top_sources": [
                    Path(h.get("source") or h.get("file") or "?").name for h in hits[:3]
                ],
            }
        )
    return rows


def eval_llm_subset(ids: set[str] | None = None) -> list[dict]:
    """Optional slower pass via talk_to_jan subprocess."""
    rows = []
    for case in CASES:
        if ids and case["id"] not in ids:
            continue
        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "talk_to_jan.py"), case["q"]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        low = out.lower()
        matched = _has_any(low, case["expect_any"])
        # groundedness line if present
        g = None
        m = re.search(r"groundedness[:\*]*\s*([0-9.]+)", low)
        if m:
            try:
                g = float(m.group(1))
            except ValueError:
                g = None
        rows.append(
            {
                "id": case["id"],
                "ok": bool(matched) and p.returncode == 0,
                "matched_keywords": matched,
                "groundedness": g,
                "rc": p.returncode,
                "chars": len(out),
            }
        )
    return rows


def write_reports(report: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(OUT_JSON, report, indent=2, min_bytes=20)
    else:
        OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"# Jan golden eval — {report['at']}",
        "",
        f"**Mode:** {report['mode']}  ",
        f"**Pass rate (retrieve):** {report['retrieve_pass']}/{report['retrieve_total']}  ",
        f"**Lane preference hits:** {report['lane_ok_count']}/{report['retrieve_total']}  ",
        "",
        "| id | ok | lane_ok | matched | top sources |",
        "|----|----|---------|---------|-------------|",
    ]
    for r in report["retrieve"]:
        lines.append(
            f"| {r['id']} | {'✅' if r['ok'] else '❌'} | {'✅' if r['lane_ok'] else '⚠'} | "
            f"{', '.join(r['matched_keywords']) or '—'} | {', '.join(r['top_sources'])} |"
        )
    if report.get("llm"):
        lines += ["", "## LLM subset", "", "| id | ok | groundedness | matched |", "|----|----|--------------|---------|"]
        for r in report["llm"]:
            lines.append(
                f"| {r['id']} | {'✅' if r['ok'] else '❌'} | {r.get('groundedness')} | "
                f"{', '.join(r.get('matched_keywords') or []) or '—'} |"
            )
    lines += [
        "",
        "## Notes",
        "- Retrieve-only is the fast nightly gate.",
        "- LLM subset optional (local Qwythos :8091).",
        "- Expected keywords are public/corpus anchors — not full author lists.",
        "",
    ]
    md_body = "\n".join(lines)
    if atomic_write_text is not None:
        atomic_write_text(OUT_MD, md_body, min_bytes=20)
    else:
        OUT_MD.write_text(md_body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--llm", action="store_true", help="also run talk_to_jan on all cases")
    ap.add_argument(
        "--llm-ids",
        default="",
        help="comma ids for llm subset (default: hi_ho_silver,conference_2026,wswtr_title)",
    )
    args = ap.parse_args()

    retrieve_rows = eval_retrieve(args.k)
    llm_rows = []
    mode = "retrieve"
    if args.llm:
        mode = "retrieve+llm"
        ids = {x.strip() for x in (args.llm_ids or "hi_ho_silver,conference_2026,wswtr_title").split(",") if x.strip()}
        llm_rows = eval_llm_subset(ids)

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "k": args.k,
        "retrieve": retrieve_rows,
        "retrieve_pass": sum(1 for r in retrieve_rows if r["ok"]),
        "retrieve_total": len(retrieve_rows),
        "lane_ok_count": sum(1 for r in retrieve_rows if r.get("lane_ok")),
        "llm": llm_rows,
        "ok": all(r["ok"] for r in retrieve_rows),
    }
    write_reports(report)
    print(json.dumps(report, indent=2)[:12000])
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
