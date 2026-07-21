#!/usr/bin/env python3
"""Extract WSWTR author surnames/lists from BooksBloom gold only.

Policy:
  - Corpus gold extracts only (K: _gold_extracts). Never invent authors.
  - Primary source: 2005-12-21 jan-authors.wpd (clean Last, First lines).
  - Secondary: "New authors added" block from WSWTR part1 final (labeled).
  - Output JSON + markdown for vault CNS; talk_to_jan can cite these packs.

Usage:
  python jan_wswtr_author_list_extract.py
  python jan_wswtr_author_list_extract.py --min-count 50
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

GOLD = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Projects"
    r"\from-g-drive\Booksbloom\_gold_extracts"
)
OUT_JSON = Path(r"D:\HermesData\state\wswtr_author_list_latest.json")
OUT_MD = Path(
    r"D:\PhronesisVault\Operations\WSWTR-Author-List-Extract-2026-07-19.md"
)
OUT_LOG = Path(r"D:\PhronesisVault\Operations\logs\wswtr-author-list-latest.json")

# Prefer explicit author-index gold first
PRIMARY = [
    "2005-12-21_-_jan-authors.wpd.md",
]
# Secondary: revised-edition "New authors added" (First Last form)
SECONDARY_NEW = [
    "2010-06-10_1451_-_WSWTR_part1_final.wpd.md",
]
# Tertiary: body heading / entry lines (Last, First) from gold WSWTR bodies only
BODY_HEADING = [
    "newwswtr313.wpd.md",
    "wswtr_extra.wpd.md",
    "2010-06-10_1451_-_WSWTR_part1_final.wpd.md",
]
# Reject false-positive "Last, First" lines from prose/places
REJECT_LAST = {
    "cokato",
    "jan bloom",
    "who should",
    "sata",
    "dlb",
    "source",
}
REJECT_FIRST_SUBSTR = (
    "who should",
    "living books",
    "http",
    "www.",
    "volume",
)

LAST_FIRST = re.compile(
    r"^(?P<last>[A-Z][A-Za-z'’\-\.]*(?:[\s][A-Z][A-Za-z'’\-\.]*){0,2}),\s*"
    r"(?P<first>.+?)\s*$"
)
# First Last (2–4 tokens) for the "New authors added" block
FIRST_LAST = re.compile(
    r"^(?P<first>[A-Z][A-Za-z'’\-\.]+(?:\s[A-Z][A-Za-z'’\-\.]+){0,2})\s+"
    r"(?P<last>[A-Z][A-Za-z'’\-\.]+)$"
)

SKIP_LINE = re.compile(
    r"^(SOURCE:|#|---|\*|❀|BLANK|WHO SHOULD|VOLUME|AUTHORS OF|Jan Bloom|"
    r"www\.|COPYRIGHT|Published|Printed|All rights|To order|New authors|"
    r"New series|Improved|Space for|Reading |Favorite |Updated |Additional |"
    r"method:|chars:|lane:|source:|extracted)",
    re.I,
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def parse_last_first_file(path: Path) -> list[dict]:
    raw = strip_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    authors: list[dict] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or SKIP_LINE.search(line):
            continue
        # drop pure noise fragments
        if len(line) < 3 or len(line) > 80:
            continue
        m = LAST_FIRST.match(line)
        if not m:
            continue
        last = m.group("last").strip(" .")
        first = m.group("first").strip(" .")
        # reject truncated tails like "Dalgle"
        if len(last) < 2 or len(first) < 1:
            continue
        key = f"{last.lower()}|{first.lower()}"
        if key in seen:
            continue
        seen.add(key)
        authors.append(
            {
                "last": last,
                "first": first,
                "display": f"{last}, {first}",
                "source_file": path.name,
                "form": "last_first",
            }
        )
    return authors


def parse_new_authors_block(path: Path) -> list[dict]:
    """Pull only the short 'New authors added' list near the top of part1 final."""
    raw = strip_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    # window after marker
    m = re.search(r"New authors added\s*(.+?)New series added", raw, re.I | re.S)
    if not m:
        return []
    block = m.group(1)
    authors: list[dict] = []
    seen: set[str] = set()
    for line in block.splitlines():
        line = line.strip().lstrip("❀•-* ").strip()
        if not line or SKIP_LINE.search(line):
            continue
        # allow multi names on one line separated by 2+ spaces
        parts = re.split(r"\s{2,}", line) if "  " in line else [line]
        for part in parts:
            part = part.strip()
            if not part:
                continue
            fm = FIRST_LAST.match(part)
            if not fm:
                continue
            first = fm.group("first").strip()
            last = fm.group("last").strip()
            key = f"{last.lower()}|{first.lower()}"
            if key in seen:
                continue
            seen.add(key)
            authors.append(
                {
                    "last": last,
                    "first": first,
                    "display": f"{last}, {first}",
                    "source_file": path.name,
                    "form": "first_last_new_authors_block",
                    "note": "from revised-edition 'New authors added' list",
                }
            )
    return authors


def _clean_body_first(first: str) -> str | None:
    """Normalize first-name field from body lines; return None if reject."""
    first = first.strip()
    # tab-separated body rows: "Louisa May\t1832 - 1888\tLittle Women..."
    if "\t" in first:
        first = first.split("\t", 1)[0].strip()
    # trailing volume markers: "Louisa May -1" / "Streeter-1"
    first = re.sub(r"\s*-\d+\s*$", "", first).strip()
    first = first.strip(" .;:")
    if not first or len(first) > 48:
        return None
    low = first.lower()
    if any(s in low for s in REJECT_FIRST_SUBSTR):
        return None
    if " by " in low or low.startswith("by "):
        return None
    # bare state/code junk
    if re.fullmatch(r"[A-Z]{2}", first):
        return None
    # ALL-CAPS multi-token codes (ABYP, JR, LOC)
    if first.isupper() and len(first) >= 2:
        return None
    # years-only junk
    if re.fullmatch(r"\d{4}(\s*-\s*\d{4})?", first):
        return None
    # must look like a personal name token sequence
    if not re.match(
        r"^[A-Z][A-Za-z'’\-\.]+(?:\s+[A-Z][A-Za-z'’\-\.]+){0,3}$",
        first,
    ):
        # allow nicknames in quotes: Isabella "Pansy"
        if not re.match(
            r"^[A-Z][A-Za-z'’\-\.]+(?:\s+[A-Z][A-Za-z'’\-\.]+)*(?:\s+[“\"][^”\"]+[”\"])?$",
            first,
        ):
            return None
    return first


def parse_body_heading_file(path: Path) -> list[dict]:
    """Deeper WSWTR body pass: Last, First entry lines only (gold file, no invention)."""
    raw = strip_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    name_l = path.name.lower()
    # part1 final: only AUTHOR INFORMATION section (tab/year entries)
    if "part1_final" in name_l:
        m = re.search(
            r"AUTHOR INFORMATION\s*(.+?)(?:\nBAAA\b|\nAPPENDIX|\Z)",
            raw,
            re.I | re.S,
        )
        if not m:
            return []
        body = m.group(1)
        require_tab_or_year = True
    else:
        body = raw
        require_tab_or_year = False

    authors: list[dict] = []
    seen: set[str] = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or SKIP_LINE.search(line):
            continue
        if len(line) < 3 or len(line) > 120:
            continue
        if require_tab_or_year and ("\t" not in line) and not re.search(r"\b1[7-9]\d{2}\b", line):
            # AUTHOR INFORMATION rows are tab/year structured; skip prose
            continue
        candidate = line.replace("\u2013", "-").replace("\u2014", "-")
        m = LAST_FIRST.match(candidate)
        if not m:
            continue
        last = m.group("last").strip(" .")
        first_raw = m.group("first").strip()
        if last.lower() in REJECT_LAST:
            continue
        if len(last) < 2 or last.isupper():
            continue
        # reject title-like lasts with internal hyphens + lowercase (Alice-All-by-Herself)
        if re.search(r"[a-z]-[a-z]", last):
            continue
        first = _clean_body_first(first_raw)
        if not first:
            continue
        if not re.search(r"[A-Za-z]", first):
            continue
        # articles/titles as "first"
        if first.lower() in {"the", "a", "an", "and", "or", "of"}:
            continue
        key = f"{last.lower()}|{first.lower()}"
        if key in seen:
            continue
        seen.add(key)
        authors.append(
            {
                "last": last,
                "first": first,
                "display": f"{last}, {first}",
                "source_file": path.name,
                "form": "body_heading_last_first",
                "note": "WSWTR body/entry line (gold only)",
            }
        )
    return authors


def build(min_count: int = 50) -> dict:
    primary_rows: list[dict] = []
    secondary_rows: list[dict] = []
    body_rows: list[dict] = []
    sources_used: list[str] = []
    warnings: list[str] = []

    for name in PRIMARY:
        p = GOLD / name
        if not p.exists():
            warnings.append(f"missing primary: {name}")
            continue
        rows = parse_last_first_file(p)
        primary_rows.extend(rows)
        sources_used.append(str(p))

    for name in SECONDARY_NEW:
        p = GOLD / name
        if not p.exists():
            warnings.append(f"missing secondary: {name}")
            continue
        rows = parse_new_authors_block(p)
        secondary_rows.extend(rows)
        sources_used.append(str(p) + "#New_authors_added")

    for name in BODY_HEADING:
        p = GOLD / name
        if not p.exists():
            warnings.append(f"missing body_heading: {name}")
            continue
        rows = parse_body_heading_file(p)
        body_rows.extend(rows)
        sources_used.append(str(p) + "#body_heading")

    # merge unique by last|first
    merged: dict[str, dict] = {}
    # Prefer primary, then secondary new-authors, then body headings
    for r in primary_rows + secondary_rows + body_rows:
        key = f"{r['last'].lower()}|{r['first'].lower()}"
        if key not in merged:
            merged[key] = r
        else:
            # keep earlier (higher-trust) form; note additional sources
            if r.get("source_file") and r.get("source_file") != merged[key].get("source_file"):
                merged[key].setdefault("also_in", []).append(r.get("source_file"))
            if r.get("form") != merged[key].get("form"):
                merged[key].setdefault("also_forms", []).append(r.get("form"))

    authors = sorted(merged.values(), key=lambda a: (a["last"].lower(), a["first"].lower()))
    report = {
        "at": utc(),
        "policy": "gold extracts only — never invent authors/ISBNs",
        "primary_count": len(primary_rows),
        "secondary_new_count": len(secondary_rows),
        "body_heading_count": len(body_rows),
        "unique_count": len(authors),
        "min_count": min_count,
        "ok": len(authors) >= min_count,
        "sources_used": sources_used,
        "warnings": warnings,
        "authors": authors,
        "public_blurb_note": (
            "Public site says 157 authors per WSWTR volume — this extract is a "
            "partial gold index (jan-authors + revised new-authors block + "
            "body-heading Last, First lines), not a claim of completeness. "
            "Never pad to 157."
        ),
    }
    return report


def write_outputs(report: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    # full JSON state + pulse receipt (atomic publish)
    if atomic_write_json is not None:
        atomic_write_json(OUT_JSON, report, indent=2, min_bytes=20)
        atomic_write_json(OUT_LOG, report, indent=2, min_bytes=20)
    else:
        OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        OUT_LOG.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "---",
        "tags:",
        "  - domain/ops",
        "  - booksbloom",
        "  - wswtr",
        "---",
        "",
        "# WSWTR author list extract (gold only)",
        "",
        f"**Generated:** {report['at']}  ",
        f"**Unique authors:** {report['unique_count']}  ",
        f"**Primary (jan-authors Last, First):** {report['primary_count']}  ",
        f"**Secondary (part1 'New authors added'):** {report['secondary_new_count']}  ",
        f"**Body heading (Last, First entries):** {report.get('body_heading_count', 0)}  ",
        f"**OK (≥{report['min_count']}):** {'yes' if report['ok'] else 'NO'}  ",
        "",
        "## Policy",
        "",
        "- Extracted **only** from K gold files listed below.",
        "- **Do not** treat as complete 157-author public blurb fulfillment.",
        "- Curator may say “on the gold author index…” and cite this pack + source file.",
        "- Never invent missing surnames to reach 157.",
        "- Body-heading pass merges extra Last, First entry lines; primary wins on conflicts.",
        "",
        "## Sources",
        "",
    ]
    for s in report["sources_used"]:
        lines.append(f"- `{s}`")
    if report["warnings"]:
        lines += ["", "## Warnings", ""]
        for w in report["warnings"]:
            lines.append(f"- {w}")
    lines += [
        "",
        "## Author index (alphabetical)",
        "",
        "| # | Author (Last, First) | Source | Form |",
        "|---|----------------------|--------|------|",
    ]
    for i, a in enumerate(report["authors"], 1):
        lines.append(
            f"| {i} | {a['display']} | `{a['source_file']}` | {a['form']} |"
        )
    lines += [
        "",
        "## Related",
        "",
        "- [[Operations/Jan-Bloom-Public-Context-2026-07-14]] (public: 157 authors/volume)",
        "- [[Operations/BooksBloom-Convention-Master-Table-2026-07-19]]",
        "- [[Operations/Jan-BooksBloom-SubSilo-Done-Definition-2026-07-18]]",
        "- Script: `D:\\\\HermesData\\\\scripts\\\\jan_wswtr_author_list_extract.py`",
        "",
    ]
    # vault note pack — atomic to avoid mid-write truncate of large author table
    md_body = "\n".join(lines)
    if atomic_write_text is not None:
        atomic_write_text(OUT_MD, md_body, min_bytes=20)
    else:
        OUT_MD.write_text(md_body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=50)
    args = ap.parse_args()
    report = build(min_count=args.min_count)
    write_outputs(report)
    slim = {k: report[k] for k in report if k != "authors"}
    slim["sample"] = [a["display"] for a in report["authors"][:15]]
    slim["out_md"] = str(OUT_MD)
    slim["out_json"] = str(OUT_JSON)
    print(json.dumps(slim, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
