#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

REG = Path(r"D:\PhronesisVault\Roleplay-Sandbox\registry")
CAND = REG / "candidates"


def main() -> int:
    rows = []
    if CAND.is_dir():
        for c in sorted(CAND.iterdir(), key=lambda p: p.name.lower()):
            if not c.is_dir():
                continue
            flags = [
                "Y" if (c / n).exists() else "-"
                for n in ("dossier.md", "meta.json", "portrait.png", "visual-tags.yaml")
            ]
            rows.append((c.name, flags))
    lines = [
        "# registry — 00-INDEX",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "## Cast lock",
        "See `CAST-LOCK-RULE.md`",
        "",
        "## Candidates",
        "| Candidate | dossier | meta | portrait | tags |",
        "|----------|---------|------|----------|------|",
    ]
    for name, f in rows:
        lines.append(f"| `{name}` | {f[0]} | {f[1]} | {f[2]} | {f[3]} |")
    lines += ["", f"**Count:** {len(rows)}", ""]
    (REG / "00-INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"registry candidates={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
