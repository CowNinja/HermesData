#!/usr/bin/env python3
"""Daily-F executor: attach living-CNS orphans to parent indexes + hub footers.

Obsidian Graph only draws edges from resolvable [[wikilinks]]. This pass:
  1) Finds orphans (no in/out wikilinks) under living folders
  2) Appends a ## Vault links footer pointing at parent 00-INDEX + domain hub
  3) Ensures the parent index lists the note as a wikilink (if index exists)

Noise folders (Alice, Roleplay-Sandbox, Archive bulk, etc.) are skipped —
hide those from Graph via .obsidian/app.json userIgnoreFilters instead.

Usage:
  python vault_hub_backlink_pass.py              # dry-run
  python vault_hub_backlink_pass.py --apply      # write changes
  python vault_hub_backlink_pass.py --apply --limit 120
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
HERMES_LOG = Path(r"D:\HermesData\logs\vault-hub-backlink-latest.json")
VAULT_LOG = VAULT / "Operations" / "logs" / "vault-hub-backlink-latest.md"
WIKI = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
L4_PAT = re.compile(r"^## Vault links\s*$", re.MULTILINE)

SKIP_PARTS = {".git", "node_modules", ".obsidian", "__pycache__"}

# Folders that should NOT get auto-backlinks (noise / sandbox / archives)
NOISE_PREFIXES = (
    "Archive/",
    "Alice/",
    "Roleplay-Sandbox/",
    "references/",
    "tests/",
    "copilot/",
    "Discord/configs/",
    "AI-Zone/Drafts/",
    "AI-Zone/exports/",
    "Operations/logs/cron-append/",
    "Operations/logs/log-intelligence/",
    "docs/agent-coordination/incidents/",
    ".smart-env/",
    "temp_sources/",
    "scripts/",
    "Backups/",
    "temp/",
)

# Domain hubs for L4 footers (first match by path prefix wins)
DOMAIN_HUBS = [
    ("Operations/", "Operations/00-INDEX"),
    ("Research/", "Research/00-INDEX"),
    ("Setup/", "Setup/00-INDEX"),
    ("Digital-Twin/", "Digital-Twin/00-INDEX"),
    ("Discord/", "Discord/00-INDEX"),
    ("docs/agent-coordination/", "docs/agent-coordination/00-INDEX"),
    ("AI-Computer-Management/", "AI-Computer-Management/00-INDEX"),
    ("SkillForge/", "SkillForge/00-INDEX"),
    ("MOCs/", "MOCs/00-INDEX"),
    ("Security/", "Security/00-INDEX"),
    ("cns/", "cns/00-INDEX"),
    ("AI-Zone/", "AI-Zone/00-INDEX"),
]

GLOBAL_HUBS = ("Housekeeping", "Archive-Index", "00-INDEX")


def relp(p: Path) -> str:
    return str(p.relative_to(VAULT)).replace("\\", "/")


def is_noise(p: Path) -> bool:
    r = relp(p)
    return any(r.startswith(n) for n in NOISE_PREFIXES)


def vault_stem(p: Path) -> str:
    r = relp(p)
    return r[:-3] if r.lower().endswith(".md") else r


def build_index(files: list[Path]) -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for p in files:
        r = relp(p)
        stem = vault_stem(p)
        idx[r.lower()] = p
        idx[stem.lower()] = p
        idx[p.stem.lower()] = p
    return idx


def resolve(target: str, source: Path, index: dict[str, Path]) -> Path | None:
    t = target.strip().replace("\\", "/")
    if t.startswith("http"):
        return None
    parent = relp(source.parent)
    cands = [t, t + ".md"]
    if parent not in (".", ""):
        cands += [f"{parent}/{t}", f"{parent}/{t}.md"]
    for c in cands:
        k = c.strip("/").lower()
        if k in index:
            return index[k]
    return None


def find_parent_index(note: Path) -> Path | None:
    parent = note.parent
    for name in ("00-INDEX.md", "INDEX.md"):
        cand = parent / name
        if cand.exists() and cand != note:
            return cand
    # walk up one more level for nested dumps
    if parent != VAULT:
        for name in ("00-INDEX.md", "INDEX.md"):
            cand = parent.parent / name
            if cand.exists():
                return cand
    root = VAULT / "00-INDEX.md"
    return root if root.exists() else None


def domain_hub_for(note: Path) -> str:
    r = relp(note)
    for prefix, hub in DOMAIN_HUBS:
        if r.startswith(prefix):
            return hub
    return "00-INDEX"


def ensure_footer(text: str, links: list[str]) -> tuple[str, bool]:
    """Return (new_text, changed)."""
    block_lines = ["## Vault links", ""] + [f"- [[{x}]]" for x in links] + [""]
    block = "\n".join(block_lines)
    if L4_PAT.search(text):
        # Merge missing wikilinks into existing section
        m = L4_PAT.search(text)
        assert m
        start = m.start()
        rest = text[m.end() :]
        # next ## heading ends section
        next_h = re.search(r"\n## ", rest)
        section = rest[: next_h.start()] if next_h else rest
        after = rest[next_h.start() :] if next_h else ""
        changed = False
        new_section = section
        for link in links:
            token = f"[[{link}"
            if token not in text:
                # append before trailing whitespace of section
                new_section = new_section.rstrip() + f"\n- [[{link}]]\n"
                changed = True
        if not changed:
            return text, False
        return text[:start] + "## Vault links" + new_section + after, True
    # append new section
    body = text.rstrip() + "\n\n" + block
    return body, True


def ensure_index_lists_note(index_path: Path, note: Path, apply: bool) -> bool:
    """Add wikilink line for note under index if missing."""
    text = index_path.read_text(encoding="utf-8", errors="replace")
    target = vault_stem(note)
    if f"[[{target}" in text or f"[[{note.stem}" in text:
        return False
    line = f"- [[{target}|{note.name}]]"
    # Prefer append under ## Files
    if "## Files" in text:
        parts = text.split("## Files", 1)
        head, tail = parts[0], parts[1]
        # insert after heading line
        nl = tail.find("\n")
        if nl >= 0:
            new_text = head + "## Files" + tail[: nl + 1] + line + "\n" + tail[nl + 1 :]
        else:
            new_text = text + "\n" + line + "\n"
    else:
        new_text = text.rstrip() + "\n\n## Linked notes\n\n" + line + "\n"
    if apply:
        index_path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes (default dry-run)")
    ap.add_argument("--limit", type=int, default=150, help="Max notes to touch per run")
    ap.add_argument("--include-indexes", action="store_true", help="Also process 00-INDEX orphans")
    args = ap.parse_args()

    files = [
        p
        for p in VAULT.rglob("*.md")
        if not any(s in p.parts for s in SKIP_PARTS)
    ]
    index = build_index(files)

    out_links: dict[Path, set[Path]] = defaultdict(set)
    in_links: dict[Path, set[Path]] = defaultdict(set)
    for src in files:
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in WIKI.finditer(text):
            dst = resolve(m.group(1).strip(), src, index)
            if dst and dst != src:
                out_links[src].add(dst)
                in_links[dst].add(src)

    orphans = [
        p
        for p in files
        if not out_links.get(p)
        and not in_links.get(p)
        and not is_noise(p)
    ]
    if not args.include_indexes:
        orphans = [
            p
            for p in orphans
            if p.name.lower() not in ("00-index.md", "index.md", "readme.md")
        ]

    orphans.sort(key=lambda p: relp(p))
    targets = orphans[: max(0, args.limit)]

    changed_notes: list[str] = []
    changed_indexes: list[str] = []
    skipped: list[str] = []

    for note in targets:
        parent_idx = find_parent_index(note)
        hub = domain_hub_for(note)
        links: list[str] = []
        if parent_idx:
            links.append(vault_stem(parent_idx))
        links.append(hub)
        for g in GLOBAL_HUBS:
            if g not in links:
                links.append(g)
        # de-dupe preserve order
        seen: set[str] = set()
        uniq: list[str] = []
        for x in links:
            xl = x.lower()
            if xl not in seen:
                seen.add(xl)
                uniq.append(x)
        links = uniq[:5]

        try:
            text = note.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(relp(note))
            continue

        new_text, note_changed = ensure_footer(text, links)
        if note_changed and args.apply:
            note.write_text(new_text, encoding="utf-8", newline="\n")
        if note_changed:
            changed_notes.append(relp(note))

        if parent_idx and parent_idx != note:
            if ensure_index_lists_note(parent_idx, note, apply=args.apply):
                changed_indexes.append(relp(parent_idx))

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "apply": bool(args.apply),
        "limit": args.limit,
        "living_orphan_candidates": len(orphans),
        "processed": len(targets),
        "notes_changed": len(changed_notes),
        "indexes_updated": len(set(changed_indexes)),
        "sample_notes": changed_notes[:40],
        "sample_indexes": sorted(set(changed_indexes))[:20],
    }
    HERMES_LOG.parent.mkdir(parents=True, exist_ok=True)
    HERMES_LOG.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    VAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    mode = "APPLY" if args.apply else "DRY-RUN"
    lines = [
        f"# Vault Hub Backlink Pass — {payload['ts'][:10]}",
        "",
        f"**Mode:** {mode} · **Living orphans (eligible):** {len(orphans)} · **Processed:** {len(targets)}",
        f"**Notes changed:** {len(changed_notes)} · **Indexes updated:** {len(set(changed_indexes))}",
        "",
        "## Sample notes",
        "",
    ]
    for s in changed_notes[:40]:
        lines.append(f"- `{s}`")
    if len(changed_notes) > 40:
        lines.append(f"- … +{len(changed_notes) - 40} more")
    lines += [
        "",
        "## Vault links",
        "",
        "- [[Operations/00-INDEX]]",
        "- [[Housekeeping]]",
        "- [[docs/agent-coordination/Vault-Link-Audit-2026-06-24]]",
        "",
    ]
    VAULT_LOG.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
