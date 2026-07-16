#!/usr/bin/env python3
"""Improved WordPerfect (.wpd) text recovery — best-effort without LibreOffice.

WP files start with \\xffWPC. Text is often in 8-bit packets mixed with function codes.
This is NOT perfect fidelity; use LibreOffice when available for full printbooks.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

OUT = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\Family\Jan-Bloom-Author\text_wpd"
)
WSWTR = Path(
    r"G:\Booksbloom\2025-01-03_Booksbloom3-HDD\Users\Admin\Documents\WSWTR"
)

HINTS = set(
    """
    the and for with that this from book books author authors read reading
    children child library home who should then keepers bloom jan gary
    family stories living great good volume chapter dedication thrift
    bookstore shelves parents young adult adults school
    """.split()
)


def recover_wpd(data: bytes, limit: int = 500_000) -> str:
    # Prefer latin-1 map of printable-ish runs after stripping WP function codes
    # WP function codes often 0x80-0xFF singles; keep A-Za-z rich runs
    text = data.decode("latin-1", errors="ignore")
    # drop obvious binary control ranges by splitting on non-printables
    pieces = re.split(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]+", text)
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for p in pieces:
        s = re.sub(r"\s+", " ", p).strip()
        if len(s) < 30:
            continue
        letters = sum(c.isalpha() for c in s)
        if letters / max(len(s), 1) < 0.55:
            continue
        words = re.findall(r"[A-Za-z']{3,}", s.lower())
        if len(words) < 5:
            continue
        sc = len(set(words) & HINTS) + min(len(words), 50) * 0.02
        if sc < 0.5:
            continue
        key = s[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    # re-order by first appearance for readability
    keep = {s for _, s in scored[:6000]}
    ordered = []
    for p in pieces:
        s = re.sub(r"\s+", " ", p).strip()
        if s in keep and s not in ordered:
            ordered.append(s)
    return "\n".join(ordered)[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(WSWTR.glob("*.wpd")) if WSWTR.exists() else []
    total = 0
    for p in files:
        data = p.read_bytes()
        if not data.startswith(b"\xffWPC"):
            print("skip_not_wp", p.name)
            continue
        body = recover_wpd(data)
        outp = OUT / (re.sub(r"[^\w.\-]+", "_", p.stem)[:80] + ".txt")
        header = f"SOURCE: {p}\nMETHOD: wpd_recover_v2\nCHARS: {len(body)}\n\n"
        outp.write_text(header + body, encoding="utf-8", errors="ignore")
        print(p.name, "chars", len(body))
        total += len(body)
    print({"files": len(files), "total_chars": total, "out": str(OUT)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
