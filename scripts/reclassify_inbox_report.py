#!/usr/bin/env python3
"""Report how _Inbox/from-g-drive files would route with current domain_route rules.

Does NOT move files (dry report). Use after expanding domain rules.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from domain_route import domain_for

INBOX = Path(
    r"K:\Phronesis-Sovereign\Personal-Digital-Silo\Core-Personal\_Inbox\from-g-drive"
)
OUT = Path(r"D:\PhronesisVault\Operations\logs\inbox-reclassify-report-latest.md")


def main() -> int:
    if not INBOX.is_dir():
        print(json.dumps({"error": "no inbox"}))
        return 1
    c: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    n = 0
    for p in INBOX.iterdir():
        if not p.is_file() or p.name.endswith(".meta.json") or ".train." in p.name:
            continue
        d = domain_for(p.name)
        c[d] += 1
        samples.setdefault(d, []).append(p.name)
        n += 1
    lines = [
        "# Inbox reclassify report (dry)",
        "",
        f"**Files:** {n}",
        "",
        "| Proposed domain | Count |",
        "|-----------------|------:|",
    ]
    for d, k in c.most_common():
        lines.append(f"| {d} | {k} |")
    lines.append("")
    for d, names in samples.items():
        if d == "Core-Personal/_Inbox":
            continue
        lines.append(f"## Would leave Inbox → `{d}`")
        for name in names[:15]:
            lines.append(f"- {name}")
        lines.append("")
    lines.append("[[Operations/logs/memorycard-trial-lessons-learned-2026-07-10]]")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"files": n, "by_domain": dict(c), "receipt": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
