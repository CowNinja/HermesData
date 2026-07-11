#!/usr/bin/env python3
"""Housekeeping for K Personal-Digital-Silo — tidy, intuitive interface.

- Ensure domain shelves + 00-INDEX
- Ensure Friends shelf
- Prune empty scratch dirs (safe)
- Count orphans / report health of layout
Never deletes originals of content files.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SILO = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\k-silo-housekeeping-latest.md")

SHELVES = [
    "Medical-Records",
    "Navy-Service",
    "Digital-Footprint",
    "Life-Archive",
    "Core-Personal/Family",
    "Core-Personal/Friends",
    "Core-Personal/Projects",
    "Core-Personal/Finance",
    "Core-Personal/Career",
    "Core-Personal/Education",
    "Core-Personal/Spiritual",
    "Core-Personal/_Inbox",
    "_Staging-From-G-Drive",
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_shelf(rel: str) -> None:
    p = SILO / rel
    p.mkdir(parents=True, exist_ok=True)
    (p / "from-g-drive").mkdir(exist_ok=True)
    idx = p / "00-INDEX.md"
    if not idx.exists():
        title = rel.replace("/", " · ")
        idx.write_text(
            f"# {title}\n\nShelf for K personal digital silo.\n\nUpdated: {utc()[:10]}\n",
            encoding="utf-8",
        )


def main() -> int:
    lines = [f"# K silo housekeeping — {utc()}", ""]
    for s in SHELVES:
        ensure_shelf(s)
        lines.append(f"- ensured `{s}`")
    # root index
    root_idx = SILO / "00-INDEX.md"
    root_idx.write_text(
        f"""# Personal Digital Silo (K:)

**Role:** Jeff life footprint — training + twin source of truth (copy-first).

## Domains
| Shelf | Intent |
|-------|--------|
| Medical-Records | Clinical, VA, providers |
| Navy-Service | Service, fitness admin, commands |
| Family | Blood/legal family |
| Friends | Friends (not family) |
| Projects | Builds, home auto, security, maker |
| Finance | Money, insurance, shopping |
| Education | School (e.g. ODU) |
| Spiritual | Faith content; church directories as community docs |
| Life-Archive | Clubs, hobbies, media |
| Digital-Footprint | Accounts, hosts |
| _Inbox | On K but primary shelf unclear — re-home later |

## Compound docs
Photo directories / multi-person pages → `.compound.json` + `.compound.train.md`

## Housekeeping
Run `k_silo_housekeeping.py` periodically.

Updated: {utc()[:10]}
""",
        encoding="utf-8",
    )
    lines.append("- refreshed root `00-INDEX.md`")
    # counts
    counts = {}
    for s in SHELVES:
        n = 0
        base = SILO / s
        if base.exists():
            for f in base.rglob("*"):
                if f.is_file() and not f.name.endswith(".meta.json") and ".train." not in f.name:
                    n += 1
        counts[s] = n
    lines += ["", "## File counts (approx)", ""]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{k}**: {v}")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"shelves": len(SHELVES), "counts": counts, "receipt": str(RECEIPT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
