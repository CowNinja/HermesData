#!/usr/bin/env python3
"""Codify Jeff temporal policy: outdated docs = historical graph/training gold, not live truth."""
from __future__ import annotations

import json
import py_compile
from datetime import datetime, timezone
from pathlib import Path

HEUR = Path(r"D:/HermesData/scripts/silo_relevance_heuristics.py")
POLICY = Path(r"D:/HermesData/config/temporal_document_policy.json")
ENTITY = Path(r"D:/HermesData/config/entity_context.json")
CANON = Path(r"D:/PhronesisVault/Operations/Temporal-Historical-Graph-Policy-CANONICAL-2026-07-14.md")

TEMPORAL_CODE = r'''

# Temporal layer (Jeff 2026-07-14): historical graph gold != current facts
# Outdated insurance/medical cards = excellent training; may not be live-relevant.


def temporal_relevance(path: str | Path, text_sample: str = "") -> str:
    """Return current | historical | unknown.

    historical = training + graph provenance; do NOT treat as live truth.
    current = prefer for day-to-day answers when docs conflict.
    """
    import re

    low = norm(path) + " " + (text_sample or "")[:2000].lower()
    years: list[int] = []
    for m in re.finditer(r"(?:19|20)\d{2}", low):
        try:
            y = int(m.group(0))
            if 1990 <= y <= 2099:
                years.append(y)
        except Exception:
            pass
    cardish = any(
        k in low
        for k in (
            "enrollment card",
            "insurance card",
            "id card",
            "member id",
            "tricare dental",
            "insurance id",
            "benefits card",
        )
    )
    if cardish and years and max(years) <= 2022:
        return "historical"
    if cardish and any(k in low for k in ("expired", "old ", "prior", "cancelled", "former")):
        return "historical"
    if years and max(years) >= 2024:
        return "current"
    if any(k in low for k in ("2024", "2025", "2026", "current", "active", "latest", "updated")):
        return "current"
    if years and max(years) <= 2022:
        return "historical"
    return "unknown"


def train_meta_flags(path: str | Path) -> dict:
    """Flags for .train.md / index: historical graph OK, not live truth."""
    t = temporal_relevance(path)
    return {
        "temporal": t,
        "twin_training_value": "high"
        if gold_tier(path) in ("twin_critical", "twin_useful")
        else "medium",
        "use_as_current_fact": t == "current",
        "use_as_historical_graph": True,
        "note": (
            "Outdated insurance/medical cards = historical gold, not current advice"
            if t == "historical"
            else ""
        ),
    }
'''


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    t = HEUR.read_text(encoding="utf-8")
    if "def temporal_relevance" in t:
        # strip old temporal block if present
        idx = t.find("# Temporal layer")
        if idx >= 0:
            t = t[:idx].rstrip() + "\n"
    t = t.rstrip() + "\n" + TEMPORAL_CODE + "\n"
    HEUR.write_text(t, encoding="utf-8")
    py_compile.compile(str(HEUR), doraise=True)

    policy = {
        "at": now,
        "jeff": (
            "Many documents have outdated information (old insurance cards, prior medical "
            "insurance for kids/me) but remain excellent for the historical graph and "
            "training. They may not be currently relevant for live answers."
        ),
        "rules": {
            "historical": (
                "keep; train; graph; never delete for age; do not answer as live fact "
                "without newer corroboration"
            ),
            "current": "prefer for day-to-day twin answers",
            "unknown": "training ok; hedge currency when answering",
        },
        "examples": [
            "TriCare enrollment cards",
            "old dental insurance",
            "prior employer benefits",
            "dated med lists",
        ],
        "api": {
            "temporal_relevance": "silo_relevance_heuristics.temporal_relevance",
            "train_meta_flags": "silo_relevance_heuristics.train_meta_flags",
        },
    }
    POLICY.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    if ENTITY.exists():
        try:
            ent = json.loads(ENTITY.read_text(encoding="utf-8"))
        except Exception:
            ent = {}
        ent["temporal_document_policy"] = policy
        ENTITY.write_text(json.dumps(ent, indent=2), encoding="utf-8")

    CANON.parent.mkdir(parents=True, exist_ok=True)
    CANON.write_text(
        f"""# Temporal / Historical Graph Policy (CANONICAL) — 2026-07-14

**Jeff:** Outdated docs (old insurance / medical cards for kids & me) are **still excellent
training and historical graph material**. They may **not** be currently relevant for live answers.

## Rules
| Temporal | Use |
|----------|-----|
| **historical** | Train + graph; never purge for age; **not** live fact without newer corroboration |
| **current** | Prefer for day-to-day twin answers |
| **unknown** | Train OK; hedge currency |

## Code
- `silo_relevance_heuristics.temporal_relevance(path)`
- `silo_relevance_heuristics.train_meta_flags(path)` → `use_as_current_fact`, `use_as_historical_graph`

## Config
`D:/HermesData/config/temporal_document_policy.json`

Updated: {now}
""",
        encoding="utf-8",
    )

    # wire train derivatives if simple
    bt = Path(r"D:/HermesData/scripts/batch_train_derivatives.py")
    if bt.exists():
        b = bt.read_text(encoding="utf-8")
        if "train_meta_flags" not in b and "temporal" not in b:
            # light touch: add import attempt in a comment block at top after docstring
            pass  # keep cook path unchanged; API available for enrich later

    import sys

    sys.path.insert(0, r"D:/HermesData/scripts")
    from silo_relevance_heuristics import temporal_relevance, train_meta_flags

    assert (
        temporal_relevance(
            r"K:/x/2017-05-01 - TriCare Dental Enrollment Card Spencer.pdf"
        )
        == "historical"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "sample_2017_card": train_meta_flags(
                    r"K:/x/2017-05-01 - TriCare Dental Enrollment Card Spencer.pdf"
                ),
                "policy": str(POLICY),
                "canon": str(CANON),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
