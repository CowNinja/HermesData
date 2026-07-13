#!/usr/bin/env python3
"""Refresh 00-INDEX.md maps in key vault folders for fast agent navigation.

Jeff intent: Hermes reads the index first to see what's in a folder before
scanning or writing. Keep lean, accurate, current.

Graph-critical: list markdown children and subfolder indexes as [[wikilinks]]
so Obsidian Graph shows real edges (backtick file lists create zero edges).

Hot-path blocks: major hubs get a fixed 'Hot paths' section so second-brain /
silo navigation survives every refresh (2026-07-13 lesson).
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
    VAULT / "Research" / "Silo-Entities",
    VAULT / "Research" / "Silo-Entities" / "orgs",
    VAULT / "Research" / "Silo-Entities" / "queries",
    VAULT / "Setup",
    VAULT / "Digital-Twin",
    VAULT / "Digital-Twin" / "receipts",
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

# Fixed hot paths re-injected every refresh (do not rely on manual edits alone)
HOT_PATHS: dict[str, list[str]] = {
    ".": [
        "| Need | Open |",
        "|------|------|",
        "| Digital twin pipeline | [[Digital-Twin/INDEX]] |",
        "| Entity PKO wiki | [[Research/Silo-Entities/00-INDEX]] |",
        "| Second-brain × silo contract | [[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]] |",
        "| Ops digests / canons | [[Operations/00-INDEX]] (hot-path table at top) |",
        "| Live silo brief | `Operations/logs/silo-status-brief-latest.md` |",
        "| D↔K harmony | [[D-K-Harmony]] |",
        "| Medical care web | [[Research/Silo-Entities/Medical-Care-Web-2017-2018]] |",
        "| Navy NCDOC net | [[Research/Silo-Entities/Navy-NCDOC-Command-Net]] |",
    ],
    "Operations": [
        "| Need | Open |",
        "|------|------|",
        "| **Semantic wiki ops** (Ingest/Query/Lint) | [[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]] |",
        "| **Which skills load** | [[Operations/Skills-Safe-Incorporate-Silo-CANONICAL-2026-07-12]] · [[Operations/Skills-Stack-Silo-Incorporation-CANONICAL-2026-07-12]] |",
        "| **One silo → many views** | [[Operations/Multi-View-Wiki-Silo-Architecture-CANONICAL-2026-07-11]] |",
        "| **PKO entity surface** | [[Research/Silo-Entities/00-INDEX]] |",
        "| **Context fabric layers** | [[Operations/Data-Silo-Context-Fabric-CANONICAL-2026-07-12]] |",
        "| **Physical priority queue** | [[Operations/Silo-Next-Enhancements-2026-07-12]] · brief: `logs/silo-status-brief-latest.md` |",
        "| **Detective -> codify** | [[Operations/Detective-Entity-Codify-Loop-CANONICAL-2026-07-11]] |",
        "| **Failure modes research** | [[Operations/Research-LLM-Wiki-Second-Brain-Failure-Modes-2026-07-13]] |",
        "",
        "Rule: **K: = raw** · **vault entity wiki = compiled**. Continuous drain stays scripts; second-brain is capped semantic densify.",
    ],
    "Research": [
        "| Need | Open |",
        "|------|------|",
        "| Silo entity PKO | [[Research/Silo-Entities/00-INDEX]] |",
        "| Life graph | [[Research/Silo-Entities/00-LIFE-GRAPH]] |",
        "| Medical care web | [[Research/Silo-Entities/Medical-Care-Web-2017-2018]] |",
        "| Navy NCDOC net | [[Research/Silo-Entities/Navy-NCDOC-Command-Net]] |",
        "| LLM-Wiki hybrid protocol | [[Research/LLM-Wiki-PhronesisVault-Integration-and-Auto-Improvement]] |",
        "| Second-brain utilization | [[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]] |",
    ],
    "Digital-Twin": [
        "| Need | Open |",
        "|------|------|",
        "| Entity PKO | [[Research/Silo-Entities/00-INDEX]] |",
        "| Second-brain loop receipt | [[Digital-Twin/receipts/second-brain-optimum-loop-2026-07-13]] |",
        "| Utilization canon | [[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]] |",
        "| Silo status brief | `Operations/logs/silo-status-brief-latest.md` |",
    ],
    "Research/Silo-Entities": [
        "| Op | Action |",
        "|----|--------|",
        "| **Ingest** | Densify person/org cards + concept hubs from OCR/dossier evidence |",
        "| **Query** | `silo_retrieve` + cards → file under `queries/` |",
        "| **Lint** | Placeholders / 0-link rows; weekly |",
        "",
        "Hubs: [[00-LIFE-GRAPH]] · [[Medical-Care-Web-2017-2018]] · [[Navy-NCDOC-Command-Net]] · [[Navy-Career-Arc]]",
        "Contract: [[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]]",
    ],
}


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
        "Research": "Curated research + Resurfaced-Ideas-CORE + Silo-Entities PKO.",
        "Research/Silo-Entities": "PKO person/org cards + concept hubs. Primary second-brain surface for silo.",
        "Research/Silo-Entities/orgs": "Organization / command entity cards.",
        "Research/Silo-Entities/queries": "Filed second-brain Query answers (cite entity cards).",
        "Setup": "Integration playbooks and environment setup.",
        "Digital-Twin": "DT pipeline, ingestion progress, receipts.",
        "Digital-Twin/receipts": "Execution receipts (second-brain loops, composer relays).",
        "Discord": "Citadel channel maps and live coordination notes (not raw configs).",
        "docs/agent-coordination": "Coordination STATUS, digests, triad protocol.",
        "AI-Computer-Management": "Desktop/sovereign computer-management track.",
        "SkillForge": "Skill trees and domain audits.",
        "MOCs": "Map-of-content hubs for graph navigation.",
        "Archive": "Recoverable history — not the working set.",
        "AI-Zone": "Ingestion / review pilots. Prefer digests over raw exports.",
    }
    return hints.get(rel, f"Folder map for agent navigation (`{rel}`). Read this before scanning all files.")


def rel_key(folder: Path) -> str:
    if folder == VAULT:
        return "."
    return str(folder.relative_to(VAULT)).replace("\\", "/")


def render_index(folder: Path) -> str:
    # Preserve auto PKO person table in Silo-Entities root index when present
    if folder == VAULT / "Research" / "Silo-Entities":
        existing = folder / "00-INDEX.md"
        if existing.exists():
            old = existing.read_text(encoding="utf-8", errors="replace")
            if "| Person | Role |" in old or "| Person | Role | Domain |" in old:
                return render_silo_entities_preserving_table(old)

    dirs, files, n_dirs, n_files = list_entries(folder)
    rel = rel_key(folder)
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
    ]

    hot = HOT_PATHS.get(rel)
    if hot:
        lines.append("## Hot paths")
        lines.extend(hot)
        lines.append("")

    lines.append("## Subfolders")
    if dirs:
        for d in dirs:
            child_idx = d / "00-INDEX.md"
            if not child_idx.exists():
                child_idx = d / "INDEX.md"
            if child_idx.exists():
                lines.append(f"- [[{vault_link(child_idx)}|{d.name}/]]")
            else:
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
    # Prefer concept hubs first for Silo-Entities-like folders
    priority = {
        "00-LIFE-GRAPH.md",
        "Medical-Care-Web-2017-2018.md",
        "Navy-NCDOC-Command-Net.md",
        "Navy-Career-Arc.md",
        "Navy-Rank-And-Legal.md",
    }
    md_files.sort(key=lambda p: (0 if p.name in priority else 1, p.name.lower()))
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
        if "Silo-Entities" in rel:
            hubs.append("[[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]]")
            hubs.append("[[Digital-Twin/INDEX]]")

    lines += ["", "## Related hubs"]
    for h in hubs:
        lines.append(f"- {h}")
    lines.append("")
    return "\n".join(lines)


def render_silo_entities_preserving_table(old: str) -> str:
    """Keep PKO person table; refresh header + hot paths + concept/file links."""
    # Extract table from first | Person | to end (or retrofill policy)
    import re

    m = re.search(r"(\| Person \|.*)", old, flags=re.S)
    table = m.group(1).rstrip() if m else ""
    dirs, files, n_dirs, n_files = list_entries(VAULT / "Research" / "Silo-Entities", max_files=200)
    lines = [
        f"# Silo entity cards — {TS}",
        "",
        "Rich PKO pages from `entity_context` + graph + registry. **Re-run** `silo_pko_entity_cards.py` to retrofill.",
        "",
        f"**Counts:** {n_dirs} dirs · {n_files} files (folder scan)",
        "",
        "## Hot paths",
    ]
    lines.extend(HOT_PATHS["Research/Silo-Entities"])
    lines += ["", "## Subfolders"]
    for d in dirs:
        child = d / "00-INDEX.md"
        if not child.exists():
            child = d / "INDEX.md"
        if child.exists():
            lines.append(f"- [[{vault_link(child)}|{d.name}/]]")
        else:
            lines.append(f"- `{d.name}/`")
    lines += ["", "## Concept / spine hubs"]
    for name in [
        "00-LIFE-GRAPH.md",
        "Medical-Care-Web-2017-2018.md",
        "Navy-NCDOC-Command-Net.md",
        "Navy-Career-Arc.md",
        "Navy-Rank-And-Legal.md",
    ]:
        p = VAULT / "Research" / "Silo-Entities" / name
        if p.exists():
            lines.append(f"- [[{vault_link(p)}|{name}]]")
    lines += ["", "## Person registry (PKO table)"]
    if table:
        lines.append(table)
    else:
        lines.append("_No person table found — run silo_pko_entity_cards.py_")
    lines += [
        "",
        "## Related hubs",
        "- [[Research/00-INDEX|parent index]]",
        "- [[Operations/Silo-Second-Brain-Loop-Utilization-CANONICAL-2026-07-13]]",
        "- [[Digital-Twin/INDEX]]",
        "- [[00-INDEX]]",
        "- [[Housekeeping]]",
        "",
    ]
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
            # create empty queries/orgs if missing
            if folder.name in {"queries", "orgs", "receipts"} and folder.parent.is_dir():
                folder.mkdir(parents=True, exist_ok=True)
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
