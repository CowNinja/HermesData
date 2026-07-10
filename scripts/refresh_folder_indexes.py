#!/usr/bin/env python3
"""Refresh 00-INDEX.md maps in key vault folders for fast agent navigation.

Jeff intent: Hermes reads the index first to see what's in a folder before
scanning or writing. Keep lean, accurate, current.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Folders that must have accurate maps after Phase B waves
TARGETS = [
    VAULT / "Operations",
    VAULT / "Operations" / "logs",
    VAULT / "Operations" / "logs" / "cron-append",
    VAULT / "Operations" / "Growth-Blueprints",
    VAULT / "Archive",
    VAULT / "Archive" / "Distillations-2026-07-10",
    VAULT / "Archive" / "Distillations-2026-07-10" / "Wave2",
    VAULT / "Archive" / "Distillations-2026-07-10" / "Wave3",
    VAULT / "Archive" / "Distillations-2026-07-10" / "Wave4",
    VAULT / "AI-Zone",
    VAULT / "AI-Zone" / "ingested",
    VAULT / "AI-Zone" / "review-moc",
    VAULT / "Discord" / "configs",
    VAULT / "Research",
    VAULT / "references",
    VAULT / "tests" / "logs",
    VAULT / "docs" / "agent-coordination",
]

SKIP_NAMES = {".git", ".obsidian", ".smart-env", "__pycache__", "node_modules"}
INDEX_NAMES = {"00-INDEX.md", "INDEX.md", "00-index.md"}


def list_entries(folder: Path, max_files: int = 80) -> tuple[list[str], list[str], int, int]:
    dirs: list[str] = []
    files: list[str] = []
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
        if p.name.startswith(".") and p.name not in (".", ".."):
            # still list important dotfiles sparingly
            if p.name not in (".gitkeep",):
                continue
        if p.is_dir():
            n_dirs += 1
            if len(dirs) < 40:
                dirs.append(p.name)
        elif p.is_file():
            n_files += 1
            if len(files) < max_files:
                try:
                    sz = p.stat().st_size
                except OSError:
                    sz = 0
                files.append(f"{p.name} ({sz}b)")
    return dirs, files, n_dirs, n_files


def purpose_for(folder: Path) -> str:
    rel = str(folder.relative_to(VAULT)).replace("\\", "/") if folder != VAULT else "vault-root"
    hints = {
        "Operations": "Living ops brain — plans, digests, STATUS, active work program. Prefer digests over dated sprawl.",
        "Operations/logs": "Execution receipts, Phase B reports, insights lessons, silo proposals. Thin rows preferred.",
        "Operations/logs/cron-append": "Thin cron one-liners + per-job INDEX-*.md. See Cron-Append-Policy.",
        "Operations/Growth-Blueprints": "High-signal research distillations (keep). Use 00-GROWTH-BLUEPRINTS-INDEX.",
        "Archive": "Recoverable history — not the working set. Prefer Distillations-2026-07-10 waves.",
        "Archive/Distillations-2026-07-10": "Phase B waves 1–4 archived originals. Each subfolder has README.",
        "AI-Zone": "Ingestion / review pilots. Working maps: ingested/, review-moc/.",
        "AI-Zone/ingested": "Live ingest stubs → es_ingest_INDEX.md; bulk archived Wave3.",
        "AI-Zone/review-moc": "MOC pilots/digests; batch noise archived Wave3–4.",
        "Discord/configs": "Category HERMES-config stubs. Master map: HERMES-CONFIG-MAP.md.",
        "Research": "Curated research + Resurfaced-Ideas-CORE.md.",
        "references": "Skill/session refs. Re-verify noise → REVERIFICATION-NOISE-INDEX + archive.",
        "tests/logs": "Test log index only in living tree; bulk archived Wave4.",
        "docs/agent-coordination": "Coordination STATUS, orchestrator canonical log, digests.",
    }
    return hints.get(rel, f"Folder map for agent navigation (`{rel}`). Read this before scanning all files.")


def render_index(folder: Path) -> str:
    dirs, files, n_dirs, n_files = list_entries(folder)
    rel = str(folder.relative_to(VAULT)).replace("\\", "/") if folder != VAULT else "."
    lines = [
        f"# {folder.name} — INDEX",
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
            lines.append(f"- `{d}/`")
        if n_dirs > len(dirs):
            lines.append(f"- … +{n_dirs - len(dirs)} more")
    else:
        lines.append("- (none)")
    lines += ["", "## Files"]
    if files:
        for f in files:
            lines.append(f"- `{f}`")
        if n_files > len(files):
            lines.append(f"- … +{n_files - len(files)} more")
    else:
        lines.append("- (none or only indexes)")
    lines += [
        "",
        "## Related hubs",
        "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
        "- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]",
        "- [[Operations/Cron-Append-Policy]]",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    done = 0
    for folder in TARGETS:
        if not folder.is_dir():
            print("SKIP missing", folder)
            continue
        # Prefer 00-INDEX.md; if only INDEX.md exists keep that name
        idx = folder / "00-INDEX.md"
        if (folder / "INDEX.md").exists() and not idx.exists():
            idx = folder / "INDEX.md"
        idx.write_text(render_index(folder), encoding="utf-8", newline="\n")
        print("OK", idx.relative_to(VAULT))
        done += 1
    # Top-level vault navigation pointer refresh (if exists keep short)
    nav = VAULT / "00-INDEX.md"
    body = f"""# PhronesisVault — Root INDEX

**Updated:** {TS}

## Purpose
Central Obsidian CNS. Agent: read folder `00-INDEX.md` before deep scans.

## Where to go
| Need | Open |
|------|------|
| Ops / digests / active work | [[Operations/00-INDEX]] · [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]] |
| Recovered archives | [[Archive/Distillations-2026-07-10/README]] |
| Research + resurfaced | [[Research/00-INDEX]] · [[Research/Resurfaced-Ideas-CORE]] |
| Discord config map | [[Discord/configs/HERMES-CONFIG-MAP]] |
| Coordination STATUS | [[docs/agent-coordination/STATUS]] |
| Grand vision | [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]] |

## Rule
Distill → archive recoverably → update this map. No landfill.
"""
    nav.write_text(body, encoding="utf-8", newline="\n")
    print("OK 00-INDEX.md (root)")
    print("done", done + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
