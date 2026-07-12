#!/usr/bin/env python3
"""Fill missing 00-INDEX.md only under living CNS folders (not Alice/Roleplay sprawl).

Uses [[wikilinks]] so new indexes create Graph edges. Weekly gardener only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Only fill under these roots (prevents VaultWalker-style index factories)
LIVING_ROOTS = {
    "Operations",
    "Research",
    "Setup",
    "Digital-Twin",
    "Discord",
    "docs",
    "AI-Computer-Management",
    "SkillForge",
    "MOCs",
    "Security",
    "Integrations",
    "Revenue",
    "cns",
    "WisdomKeeper",
    "Agents",
    "Guides",
    "Dashboard",
    "Resilience",
    "Meta",
    "Diagnostics",
    "AI-Zone",
}

SKIP = {
    ".git",
    "node_modules",
    "__pycache__",
    ".obsidian",
    ".smart-env",
    "venv",
    "Alice",
    "Roleplay-Sandbox",
    "Archive",
    "copilot",
    "references",
    "tests",
    "temp",
    "temp_sources",
    "scripts",
}


def vault_link(path: Path) -> str:
    rel = path.relative_to(VAULT)
    if rel.suffix.lower() == ".md":
        rel = rel.with_suffix("")
    return str(rel).replace("\\", "/")


def under_living(d: Path) -> bool:
    try:
        rel = d.relative_to(VAULT)
    except ValueError:
        return False
    if len(rel.parts) == 0:
        return False
    return rel.parts[0] in LIVING_ROOTS


def main() -> int:
    filled = 0
    for d in sorted(VAULT.rglob("*")):
        if not d.is_dir():
            continue
        if any(x in d.parts for x in SKIP):
            continue
        if not under_living(d):
            continue
        if (d / "00-INDEX.md").exists() or (d / "INDEX.md").exists():
            continue
        try:
            kids = list(d.iterdir())
        except OSError:
            continue
        files = [p for p in kids if p.is_file() and p.name not in ("00-INDEX.md", "INDEX.md")]
        dirs = [p for p in kids if p.is_dir() and p.name not in SKIP]
        rel = str(d.relative_to(VAULT)).replace("\\", "/")
        lines = [
            f"# {d.name} — INDEX",
            "",
            f"**Path:** `{rel}`  ",
            f"**Updated:** {TS}  ",
            f"**Counts:** {len(dirs)} dirs · {len(files)} files",
            "",
            "## Purpose",
            "Folder map for agent navigation. Read this before scanning all files.",
            "",
            "## Subfolders",
        ]
        if dirs:
            for x in sorted(dirs, key=lambda p: p.name.lower())[:40]:
                cidx = x / "00-INDEX.md"
                if not cidx.exists():
                    cidx = x / "INDEX.md"
                if cidx.exists():
                    lines.append(f"- [[{vault_link(cidx)}|{x.name}/]]")
                else:
                    lines.append(f"- `{x.name}/`")
        else:
            lines.append("- (none)")
        lines += ["", "## Files"]
        md = [p for p in files if p.suffix.lower() == ".md"]
        other = [p for p in files if p.suffix.lower() != ".md"]
        if md or other:
            for x in sorted(md, key=lambda p: p.name.lower())[:60]:
                lines.append(f"- [[{vault_link(x)}|{x.name}]]")
            for x in sorted(other, key=lambda p: p.name.lower())[:20]:
                lines.append(f"- `{x.name}`")
        else:
            lines.append("- (none)")
        parent_hub = "00-INDEX"
        if d.parent != VAULT:
            pidx = d.parent / "00-INDEX.md"
            if pidx.exists():
                parent_hub = vault_link(pidx)
        lines += [
            "",
            "## Related hubs",
            f"- [[{parent_hub}|parent]]",
            "- [[00-INDEX]]",
            "- [[Housekeeping]]",
            "",
        ]
        (d / "00-INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        filled += 1
        print("FILLED", rel)

    print(f"filled_missing={filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
