#!/usr/bin/env python3
"""Propose domain placement for high-signal test-ingest paths (no moves).

Open taxonomy matching — adaptable. Writes proposal MD only.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
TI = ROOT / "test-ingest-2026-06-25"
OUT = Path(r"D:\PhronesisVault\Operations\logs\k-test-ingest-domain-propose-latest.md")
OUT_JSON = Path(r"D:\HermesData\logs\k-test-ingest-domain-propose-latest.json")

# keyword → broad domain (open list)
RULES: list[tuple[str, list[str]]] = [
    ("Medical-Records", [r"medical", r"dental", r"diagnosis", r"prescription", r"bumed", r"med\.navy", r"lab", r"health"]),
    ("Core-Personal/Finance", [r"finance", r"navy.?cash", r"tax", r"1095", r"w-2", r"w2", r"mint", r"bank", r"mastercard", r"navyfederal"]),
    ("Navy-Service", [r"navy", r"orders", r"award", r"service.?record", r"ncdoc", r"tycon"]),
    ("Core-Personal/Career", [r"resume", r"career", r"performance.?review", r"civilian"]),
    ("Core-Personal/Education", [r"education", r"transcript", r"course", r"degree", r"school", r"college"]),
    ("Core-Personal/Spiritual", [r"spiritual", r"faith", r"church", r"ministry"]),
    ("Core-Personal/Family", [r"family", r"wedding", r"kids", r"spouse"]),
    ("Core-Personal/Projects", [r"project", r"hobby", r"maker"]),
    ("Life-Archive", [r"photo", r"video", r"correspondence", r"writing", r"letter"]),
    ("Digital-Footprint", [r"gmail", r"export", r"account", r"social", r"facebook", r"linkedin"]),
]


def classify(path: str) -> str:
    low = path.lower()
    scores: Counter[str] = Counter()
    for domain, pats in RULES:
        for pat in pats:
            if re.search(pat, low):
                scores[domain] += 1
    if not scores:
        return "Core-Personal/_Inbox"
    return scores.most_common(1)[0][0]


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    if not TI.exists():
        print(json.dumps({"error": "no test-ingest"}))
        return 1

    # sample highsignal + top-level folders only for speed
    samples: list[Path] = []
    hs = TI / "root-highsignal-sample"
    if hs.is_dir():
        for p in hs.rglob("*"):
            if p.is_file() and p.name.lower() != "desktop.ini":
                samples.append(p)
                if len(samples) >= 400:
                    break
    if len(samples) < 50:
        for p in TI.rglob("*"):
            if p.is_file() and p.name.lower() != "desktop.ini":
                samples.append(p)
                if len(samples) >= 400:
                    break

    by_domain: dict[str, list[str]] = defaultdict(list)
    for f in samples:
        rel = str(f.relative_to(TI))
        dom = classify(rel + " " + f.name)
        if len(by_domain[dom]) < 12:
            by_domain[dom].append(rel)

    counts = {d: len([1 for f in samples if classify(str(f.relative_to(TI)) + " " + f.name) == d]) for d in by_domain}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": ts, "sampled": len(samples), "counts": counts, "examples": dict(by_domain)}
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# K test-ingest → domain propose — {ts[:10]}",
        "",
        "**Mode:** proposal only — no moves",
        f"**Sampled files:** {len(samples)}",
        "",
        "Open taxonomy matching. Unmatched → `Core-Personal/_Inbox`.",
        "",
        "## Counts (sample)",
        "| Domain | ~files |",
        "|--------|-------:|",
    ]
    for d, n in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{d}` | {n} |")
    lines += ["", "## Example paths (cap 12 each)"]
    for d, ex in sorted(by_domain.items()):
        lines.append(f"### {d}")
        for e in ex:
            lines.append(f"- `{e}`")
        lines.append("")
    lines += [
        "## Next waves (suggested order)",
        "1. Medical-Records (already piloted Diagnosis-History)",
        "2. Core-Personal/Finance (Navy-Cash piloted)",
        "3. Navy-Service highsignal",
        "4. Digital-Footprint / Gmail exports (large — tranche carefully)",
        "5. Rest → _Inbox then promote domains if patterns repeat",
        "",
        "## Links",
        "- [[Operations/K-Life-Domain-Taxonomy-CANONICAL-2026-07-10]]",
        "- [[Operations/K-Silo-Holistic-Foundation-2026-07-10]]",
        "- [[Operations/logs/k-pilot-wave-receipt-latest]]",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"sampled": len(samples), "domains": len(counts), "md": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
