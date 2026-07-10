#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
SKIP = {
    ".git",
    "node_modules",
    "__pycache__",
    ".obsidian",
    ".smart-env",
    "venv",
    "alice_venv",
    "site-packages",
    "tmp",
    "asar-check-tmp",
    "asar-patch-tmp",
    "_corrupt_oneline_restore",
    ".github",
}


def main() -> int:
    filled = 0
    for d in sorted(VAULT.rglob("*")):
        if not d.is_dir():
            continue
        if any(x in d.parts for x in SKIP):
            continue
        if (d / "00-INDEX.md").exists() or (d / "INDEX.md").exists():
            continue
        kids = list(d.iterdir())
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
            lines.extend(f"- `{x.name}/`" for x in sorted(dirs, key=lambda p: p.name.lower())[:40])
        else:
            lines.append("- (none)")
        lines += ["", "## Files"]
        if files:
            lines.extend(f"- `{x.name}`" for x in sorted(files, key=lambda p: p.name.lower())[:60])
        else:
            lines.append("- (none)")
        lines += ["", "## Related hubs", "- [[00-INDEX]]", ""]
        (d / "00-INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        filled += 1

    total = either = 0
    for d in VAULT.rglob("*"):
        if not d.is_dir():
            continue
        if any(x in d.parts for x in SKIP):
            continue
        total += 1
        if (d / "00-INDEX.md").exists() or (d / "INDEX.md").exists():
            either += 1
    print(f"filled_missing={filled}")
    print(f"dirs={total} with_index={either} without={total - either}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
