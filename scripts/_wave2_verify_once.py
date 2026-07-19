#!/usr/bin/env python3
"""Independent dual-verify for wave-2 link clarity cook."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

V = Path(r"D:\PhronesisVault")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(\|[^\]]+)?\]\]")
SKIP = {".obsidian", "site-packages", "node_modules", ".git", "alice_venv", "backups"}


def build():
    stems, paths = set(), set()
    for pat in ("*.md", "*.base", "*.canvas"):
        for p in V.rglob(pat):
            if any(x in p.parts for x in SKIP):
                continue
            if "Distillations-2026-07-10" in p.parts:
                continue
            if "Roleplay-Sandbox" in p.parts and "_archive" in p.parts:
                continue
            rel = str(p.relative_to(V)).replace("\\", "/")
            rel0 = rel.rsplit(".", 1)[0]
            paths.add(rel0)
            paths.add(rel0.lower())
            paths.add(rel)
            stems.add(p.stem)
            stems.add(p.stem.lower())
    return stems, paths


def exists(t, stems, paths):
    t = t.strip().replace("\\", "/")
    if t.startswith("http"):
        return True
    if t.endswith(".md"):
        t = t[:-3]
    ts = t.rstrip("/")
    if t in paths or t.lower() in paths or ts in paths or ts.lower() in paths:
        return True
    name = Path(ts).name
    if name in stems or name.lower() in stems:
        return True
    for c in (
        V / f"{t}.md",
        V / f"{t}.base",
        V / f"{ts}.md",
        V / f"{ts}.base",
        V / f"{t}.json",
        V / f"{ts}.json",
        V / t,
        V / ts,
    ):
        if c.exists():
            return True
    return False


def main():
    stems, paths = build()
    un = []
    for p in V.rglob("*.md"):
        if any(x in p.parts for x in SKIP):
            continue
        if "Distillations-2026-07-10" in p.parts:
            continue
        if "Roleplay-Sandbox" in p.parts and "_archive" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in LINK_RE.finditer(text):
            raw = m.group(1).strip()
            if not exists(raw, stems, paths):
                un.append(raw)
    top = Counter(un).most_common(15)
    crit = [
        "Operations/Session-Reports-2026-06-19-MASTER",
        "Bases/Domain-Tag-Index",
        "Bases/Setup-Playbooks",
        "references/REVERIFICATION-NOISE-INDEX",
        "Research/Silo-Entities/dr-kapoor",
        "Research/Silo-Entities/dr-foster",
        "Research/Silo-Entities/richardson",
        "Operations/VaultWalker-Snapshots-INDEX",
        "Operations/Vault-Link-Lint-latest",
        "Operations/logs/wave2-link-clarity-cook-latest",
        "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    ]
    crit_ok = {c: exists(c, stems, paths) for c in crit}
    payload = {
        "unresolved": len(un),
        "top": top,
        "critical_ok": crit_ok,
        "phronesisvault_remaining": sum(1 for x in un if "phronesisvault" in x.lower()),
        "all_critical": all(crit_ok.values()),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_critical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
