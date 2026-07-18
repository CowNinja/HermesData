#!/usr/bin/env python3
"""Structural lint: six-law canons + Ops hot paths + critical wikilinks.

No LLM. Exit 0 if all critical paths exist.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OPS = VAULT / "Operations"
OUT = OPS / "logs" / "canon-structural-lint-latest.md"
JSON = Path(r"D:\HermesData\state\canon_structural_lint_latest.json")

SIX_LAW = [
    OPS / "Grok-Thread-Architecture-Judgment-CANONICAL-2026-07-18.md",
    OPS / "Four-Worlds-Silo-Architecture-CANONICAL-2026-07-10.md",
    OPS / "Hybrid-Local-Grok-Token-Policy-CANONICAL-2026-07-17.md",
    OPS / "VaultWalker-PhronesisVault-Focus-0.8.0-2026-07-17.md",
    OPS / "SINGLE-GATEWAY-RESTORE.md",
    OPS / "Vault-Hygiene-Cadence-CANONICAL-2026-07-12.md",
]

EXTRA = [
    OPS / "SOUL-Grok-Architecture-Agent-2026-07-18.md",
    OPS / "SOUL-Data-Silo-Agent-2026-07-17.md",
    OPS / "VaultWalker-LIVE-Decision-Card-2026-07-18.md",
    OPS / "logs" / "silo-thread-merge-handoff-2026-07-18.md",
    OPS / "00-INDEX.md",
]

HOT_NEEDLES = [
    "Grok-Thread-Architecture-Judgment-CANONICAL-2026-07-18",
    "VaultWalker-PhronesisVault-Focus-0.8.0-2026-07-17",
    "Hybrid-Local-Grok-Token-Policy-CANONICAL-2026-07-17",
    "SINGLE-GATEWAY-RESTORE",
]


def resolve_wikilink(link: str) -> Path | None:
    """Best-effort resolve [[path]] or [[path|label]] under vault."""
    link = link.strip()
    if "|" in link:
        link = link.split("|", 1)[0].strip()
    # drop anchor
    link = link.split("#", 1)[0].strip()
    if not link:
        return None
    candidates = [
        VAULT / f"{link}.md",
        VAULT / link,
        VAULT / f"{link}/00-INDEX.md",
        VAULT / f"{link}/INDEX.md",
        OPS / f"{Path(link).name}.md" if not link.startswith("Operations") else VAULT / f"{link}.md",
    ]
    # Operations/Foo without .md
    if link.startswith("Operations/") or link.startswith("Research/"):
        candidates.insert(0, VAULT / f"{link}.md")
    for c in candidates:
        if c.is_file():
            return c
    return None


def main() -> int:
    missing_files = [str(p) for p in SIX_LAW + EXTRA if not p.is_file()]
    ops_index = OPS / "00-INDEX.md"
    hot_ok = []
    hot_bad = []
    if ops_index.is_file():
        text = ops_index.read_text(encoding="utf-8", errors="ignore")
        for n in HOT_NEEDLES:
            if n in text:
                hot_ok.append(n)
            else:
                hot_bad.append(n)
    else:
        hot_bad = list(HOT_NEEDLES)

    # wikilinks inside six-law docs
    broken = []
    checked = 0
    for doc in SIX_LAW:
        if not doc.is_file():
            continue
        body = doc.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\[\[([^\]]+)\]\]", body):
            checked += 1
            target = resolve_wikilink(m.group(1))
            if target is None:
                # allow bare non-path labels lightly
                raw = m.group(1).split("|")[0].strip()
                if "/" not in raw and not raw.endswith(".md"):
                    # might be note name — try rglob expensive skip; count soft
                    soft = list(OPS.glob(f"{raw}.md")) + list(VAULT.glob(f"{raw}.md"))
                    if soft:
                        continue
                broken.append({"from": str(doc.relative_to(VAULT)), "link": m.group(1)[:120]})

    # critical broken only: links that look like paths
    broken_critical = [b for b in broken if "/" in b["link"] or b["link"].endswith(".md")]

    ok = not missing_files and not hot_bad and len(broken_critical) == 0
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "missing_files": missing_files,
        "hot_ok": hot_ok,
        "hot_bad": hot_bad,
        "wikilinks_checked": checked,
        "broken_critical": broken_critical[:40],
        "broken_total_incl_soft": len(broken),
    }
    JSON.parent.mkdir(parents=True, exist_ok=True)
    JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Canon structural lint — {payload['at']}",
        "",
        f"**OK:** {'✅ PASS' if ok else '❌ FAIL'}",
        "",
        "## Six-law + SOUL extras (existence)",
    ]
    for p in SIX_LAW + EXTRA:
        mark = "✅" if p.is_file() else "❌"
        lines.append(f"- {mark} `{p.relative_to(VAULT) if p.is_relative_to(VAULT) else p}`")
    lines += ["", "## Ops 00-INDEX hot needles", ""]
    for n in hot_ok:
        lines.append(f"- ✅ `{n}`")
    for n in hot_bad:
        lines.append(f"- ❌ missing `{n}`")
    lines += [
        "",
        f"## Wikilinks in six-law docs: checked {checked}, critical broken {len(broken_critical)}",
        "",
    ]
    if broken_critical:
        for b in broken_critical[:25]:
            lines.append(f"- ❌ `{b['from']}` → `[[{b['link']}]]`")
    else:
        lines.append("- ✅ no critical path-style broken links")
    lines += ["", f"JSON: `{JSON}`", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, indent=2)[:2500])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
