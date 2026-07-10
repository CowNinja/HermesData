#!/usr/bin/env python3
"""Ensure K Personal-Digital-Silo broad domain shelves exist (open taxonomy).

Idempotent. No deletes. Creates dirs + thin 00-INDEX maps only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"K:\Phronesis-Sovereign\Personal-Digital-Silo")
VAULT_RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\k-domain-shelves-ensure-latest.md")
TAXONOMY = Path(r"D:\PhronesisVault\Operations\K-Life-Domain-Taxonomy-CANONICAL-2026-07-10.md")

# Open starter list — adaptable; new broad domains may be added later
SHELVES = [
    ROOT / "Medical-Records",
    ROOT / "Core-Personal" / "Finance",
    ROOT / "Core-Personal" / "Career",
    ROOT / "Core-Personal" / "Education",
    ROOT / "Core-Personal" / "Spiritual",
    ROOT / "Core-Personal" / "Family",
    ROOT / "Core-Personal" / "Projects",
    ROOT / "Core-Personal" / "_Inbox",
    ROOT / "Navy-Service",
    ROOT / "Life-Archive",
    ROOT / "Digital-Footprint",
    ROOT / "Archive",
]


def write_index(d: Path, ts: str) -> None:
    rel = d.relative_to(ROOT) if d.is_relative_to(ROOT) else d
    kids = sorted(p.name for p in d.iterdir() if p.name != "00-INDEX.md") if d.is_dir() else []
    lines = [
        f"# {d.name} — INDEX",
        "",
        f"**Path:** `{rel}`",
        f"**Updated:** {ts}",
        "",
        "Broad life-domain shelf (open taxonomy). SSOT: vault `Operations/K-Life-Domain-Taxonomy-CANONICAL-2026-07-10.md`",
        "Foundation: vault `Operations/K-Silo-Holistic-Foundation-2026-07-10.md`",
        "",
        "## Contents",
    ]
    lines += [f"- `{k}`" for k in kids] if kids else ["- (empty — ready for ingest)"]
    lines += ["", "## Rules", "- Prefer this shelf over new micro-folders", "- Unsure → `Core-Personal/_Inbox` or test-ingest", ""]
    (d / "00-INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    created, refreshed = [], []
    for d in SHELVES:
        existed = d.is_dir()
        d.mkdir(parents=True, exist_ok=True)
        write_index(d, ts)
        (created if not existed else refreshed).append(str(d.relative_to(ROOT)))

    # Root index
    kids = sorted(p.name for p in ROOT.iterdir() if not p.name.startswith("."))
    (ROOT / "00-INDEX.md").write_text(
        "\n".join(
            [
                "# Personal-Digital-Silo — INDEX",
                "",
                "**World 3** · centralized life / digital footprint SSOT",
                f"**Updated:** {ts}",
                "",
                "## Open taxonomy",
                "Medical-Records · Core-Personal/{Finance,Career,Education,Spiritual,Family,Projects,_Inbox} · Navy-Service · Life-Archive · Digital-Footprint · Archive",
                "Staging: test-ingest-*",
                "",
                f"Vault SSOT: `{TAXONOMY}`",
                "Holistic: `D:\\PhronesisVault\\Operations\\K-Silo-Holistic-Foundation-2026-07-10.md`",
                "",
                "## Top-level",
                *[f"- `{k}`" for k in kids],
                "",
                "## Agent rules",
                "1. Broad domains over rabbit holes",
                "2. test-ingest / _Inbox = staging",
                "3. No RP on K",
                "4. Copy + provenance; no silent deletes",
                "5. New domain OK when pattern repeats (open list)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    VAULT_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    VAULT_RECEIPT.write_text(
        "\n".join(
            [
                f"# K domain shelves ensure — {ts}",
                "",
                f"**Created:** {len(created)} · **Refreshed indexes:** {len(refreshed) + len(created)}",
                "",
                "## Shelves",
                *[f"- `{s}`" for s in SHELVES],
                "",
                "[[Operations/K-Life-Domain-Taxonomy-CANONICAL-2026-07-10]]",
                "[[Operations/K-Silo-Holistic-Foundation-2026-07-10]]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"created": created, "refreshed_count": len(SHELVES), "receipt": str(VAULT_RECEIPT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
