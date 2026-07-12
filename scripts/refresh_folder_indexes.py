#!/usr/bin/env python3
"""Refresh 00-INDEX.md maps in key vault folders for fast agent navigation.

Jeff intent: Hermes reads the index first to see what's in a folder before
scanning or writing. Keep lean, accurate, current.

Graph-critical: list markdown children and subfolder indexes as [[wikilinks]]
so Obsidian Graph shows real edges (backtick file lists create zero edges).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Living CNS folders that must have accurate, wikilinked maps
TARGETS = [
    VAULT,
    VAULT / "Operations",
    VAULT / "Operations" / "logs",
    VAULT / "Operations" / "Growth-Blueprints",
    VAULT / "Operations" / "Audits",
    VAULT / "Research",
    VAULT / "Setup",
    VAULT / "Digital-Twin",
    VAULT / "Discord",
    VAULT / "docs" / "agent-coordination",
    VAULT / "AI-Computer-Management",
    VAULT / "AI-Computer-Management" / "Current-State",
    VAULT / "SkillForge",
    VAULT / "MOCs",
    VAULT / "Security",
    VAULT / "Integrations",
    VAULT / "Revenue",
    VAULT / "cns",
    VAULT / "WisdomKeeper",
    VAULT / "Agents",
    VAULT / "Guides",
    VAULT / "Dashboard",
    VAULT / "Resilience",
    VAULT / "Meta",
    VAULT / "Diagnostics",
    VAULT / "AI-Zone",
    VAULT / "AI-Zone" / "ingested",
    VAULT / "AI-Zone" / "review-moc",
    VAULT / "Archive",
    VAULT / "Archive" / "Distillations-2026-07-10",
]

SKIP_NAMES = {".git", ".obsidian", ".smart-env", "__pycache__", "node_modules", "Alice", "Roleplay-Sandbox"}
INDEX_NAMES = {"00-INDEX.md", "INDEX.md", "00-index.md"}


def vault_link(path: Path) -> str:
    """Wikilink target relative to vault, without .md."""
    rel = path.relative_to(VAULT)
    if rel.suffix.lower() == ".md":
        rel = rel.with_suffix("")
    return str(rel).replace("\\", "/")


def list_entries(folder: Path, max_files: int = 100) -> tuple[list[Path], list[Path], int, int]:
    dirs: list[Path] = []
    files: list[Path] = []
    if not folder.is_dir():
        return dirs, files, 0, 0
    try:
        kids = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return dirs, files, 0, 0
    n_dirs = n_files = 0
    for p in kids:
        if p.name in SKIP_NAMES or p.name in INDEX_NAMES:
            continue
        if p.name.startswith(".") and p.name not in (".gitkeep",):
            continue
        if p.is_dir():
            n_dirs += 1
            if len(dirs) < 50:
                dirs.append(p)
        elif p.is_file():
            n_files += 1
            if len(files) < max_files:
                files.append(p)
    return dirs, files, n_dirs, n_files


def purpose_for(folder: Path) -> str:
    if folder == VAULT:
        return "Central Obsidian CNS. Agent: read folder 00-INDEX.md before deep scans."
    rel = str(folder.relative_to(VAULT)).replace("\\", "/")
    hints = {
        "Operations": "Living ops brain — plans, digests, STATUS, active work. Prefer digests over dated sprawl.",
        "Operations/logs": "Execution receipts, Phase B reports, insights. Thin rows preferred.",
        "Operations/Growth-Blueprints": "High-signal research distillations. Use 00-GROWTH-BLUEPRINTS-INDEX if present.",
        "Operations/Audits": "Ops audit artifacts and health snapshots.",
        "Research": "Curated research + Resurfaced-Ideas-CORE.",
        "Setup": "Integration playbooks and environment setup.",
        "Digital-Twin": "DT pipeline, ingestion progress, receipts.",
        "Discord": "Citadel channel maps and live coordination notes (not raw configs).",
        "docs/agent-coordination": "Coordination STATUS, digests, triad protocol.",
        "AI-Computer-Management": "Desktop/sovereign computer-management track.",
        "SkillForge": "Skill trees and domain audits.",
        "MOCs": "Map-of-content hubs for graph navigation.",
        "Archive": "Recoverable history — not the working set.",
        "AI-Zone": "Ingestion / review pilots. Prefer digests over raw exports.",
    }
    return hints.get(rel, f"Folder map for agent navigation (`{rel}`). Read this before scanning all files.")


def render_index(folder: Path) -> str:
    dirs, files, n_dirs, n_files = list_entries(folder)
    rel = "." if folder == VAULT else str(folder.relative_to(VAULT)).replace("\\", "/")
    title = "PhronesisVault — Root INDEX" if folder == VAULT else f"{folder.name} — INDEX"
    lines = [
        f"# {title}",
        "",
        f"**Path:** `{rel}`  ",
        f"**Updated:** {TS}  ",
        f"**Counts:** {n_dirs} dirs · {n_files} files (listed up to cap)",
        "",
        "## Purpose",
        purpose_for(folder),
        "",
        "## Agent instructions",
        "1. Read this index first.",
        "2. Open only the named digests/maps you need.",
        "3. Prefer writing digests/updates here over creating dated dump files.",
        "4. Archives are recoverable under `Archive/Distillations-2026-07-10/`.",
        "",
        "## Subfolders",
    ]
    if dirs:
        for d in dirs:
            child_idx = d / "00-INDEX.md"
            if not child_idx.exists():
                child_idx = d / "INDEX.md"
            if child_idx.exists():
                lines.append(f"- [[{vault_link(child_idx)}|{d.name}/]]")
            else:
                # Link folder via first .md if any; else backtick
                md_kids = sorted(d.glob("*.md"))
                if md_kids:
                    lines.append(f"- [[{vault_link(md_kids[0])}|{d.name}/]] (no folder index)")
                else:
                    lines.append(f"- `{d.name}/`")
        if n_dirs > len(dirs):
            lines.append(f"- … +{n_dirs - len(dirs)} more")
    else:
        lines.append("- (none)")

    lines += ["", "## Files"]
    md_files = [p for p in files if p.suffix.lower() == ".md"]
    other_files = [p for p in files if p.suffix.lower() != ".md"]
    if md_files or other_files:
        for p in md_files:
            lines.append(f"- [[{vault_link(p)}|{p.name}]]")
        for p in other_files:
            try:
                sz = p.stat().st_size
            except OSError:
                sz = 0
            lines.append(f"- `{p.name}` ({sz}b)")
        if n_files > len(files):
            lines.append(f"- … +{n_files - len(files)} more")
    else:
        lines.append("- (none or only indexes)")

    # Parent + root hubs for bidirectional graph orientation
    hubs = ["[[00-INDEX]]", "[[Housekeeping]]", "[[Archive-Index]]"]
    if folder != VAULT:
        parent = folder.parent
        if parent == VAULT:
            hubs.insert(0, "[[00-INDEX|vault root]]")
        else:
            pidx = parent / "00-INDEX.md"
            if not pidx.exists():
                pidx = parent / "INDEX.md"
            if pidx.exists():
                hubs.insert(0, f"[[{vault_link(pidx)}|parent index]]")
        if (VAULT / "Operations" / "00-INDEX.md").exists() and "Operations" not in rel:
            hubs.append("[[Operations/00-INDEX]]")

    lines += ["", "## Related hubs"]
    for h in hubs:
        lines.append(f"- {h}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    done = 0
    for folder in TARGETS:
        if folder == VAULT:
            idx = VAULT / "00-INDEX.md"
            idx.write_text(render_index(folder), encoding="utf-8", newline="\n")
            print("OK 00-INDEX.md (root)")
            done += 1
            continue
        if not folder.is_dir():
            print("SKIP missing", folder)
            continue
        idx = folder / "00-INDEX.md"
        if (folder / "INDEX.md").exists() and not idx.exists():
            idx = folder / "INDEX.md"
        idx.write_text(render_index(folder), encoding="utf-8", newline="\n")
        print("OK", idx.relative_to(VAULT))
        done += 1
    print("done", done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
