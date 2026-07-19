#!/usr/bin/env python3
"""Lint PhronesisVault hot paths for missing domain/* tags.

Reports markdown notes under key folders that lack a #domain/ or tags: domain/
token. Non-destructive. Writes latest report under Operations/logs/.

Usage:
  python D:\\HermesData\\scripts\\vault_domain_tag_lint.py
  python D:\\HermesData\\scripts\\vault_domain_tag_lint.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
REPORT_MD = VAULT / "Operations" / "logs" / "domain-tag-lint-latest.md"
REPORT_JSON = VAULT / "Operations" / "logs" / "domain-tag-lint-latest.json"

# Hot paths only — not whole vault (Archive/logs noise excluded)
HOT_GLOBS = [
    "Operations/*.md",
    "Setup/*.md",
    "Research/*.md",
    "Research/Silo-Entities/*.md",
    "Digital-Twin/*.md",
    "Digital-Twin/**/*.md",
    "MOCs/*.md",
    "Guides/*.md",
    "Templates/*.md",
    "Bases/*.md",
    "Housekeeping.md",
    "00-INDEX.md",
    "AGENTS.md",
]

SKIP_NAME_PARTS = (
    "/logs/",
    "\\logs\\",
    "/archive/",
    "\\archive\\",
    "Distillations-",
    ".obsidian",
    "node_modules",
    "/.git/",
    "\\venv\\",
    "/venv/",
)

DOMAIN_RE = re.compile(
    r"(?:^|\s)(?:#domain/[\w-]+|tags:\s*(?:\[[^\]]*domain/|.*\n(?:\s*-\s*)?domain/))",
    re.I | re.M,
)
DOMAIN_SIMPLE = re.compile(r"domain/[\w-]+", re.I)
FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def iter_hot_files() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for g in HOT_GLOBS:
        for p in VAULT.glob(g):
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            s = str(p)
            if any(x in s for x in SKIP_NAME_PARTS):
                continue
            # Skip live Templater source templates (tags are dynamic JS)
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:800]
                if "<%" in head and "Templates" in s.replace("\\", "/"):
                    continue
            except OSError:
                pass
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
    return sorted(out, key=lambda p: str(p).lower())


def has_domain_tag(text: str) -> bool:
    if DOMAIN_SIMPLE.search(text):
        # Prefer real tag usage in frontmatter tags or body hashtags
        if re.search(r"#domain/[\w-]+", text):
            return True
        m = FM_RE.match(text)
        if m and "domain/" in m.group(1):
            return True
        # bare domain/ in body without # is weak — still count if in tags list line
        if re.search(r"(?m)^\s*-\s*domain/[\w-]+\s*$", text):
            return True
        if re.search(r"(?m)^tags:\s*\[[^\]]*domain/", text):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not VAULT.is_dir():
        print("VAULT_MISSING", VAULT, file=sys.stderr)
        return 2

    files = iter_hot_files()
    missing: list[dict] = []
    tagged: list[str] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            missing.append({"path": str(p.relative_to(VAULT)), "error": str(e)})
            continue
        rel = str(p.relative_to(VAULT)).replace("\\", "/")
        if has_domain_tag(text):
            tagged.append(rel)
        else:
            missing.append({"path": rel, "bytes": p.stat().st_size})

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "generated": now,
        "vault": str(VAULT),
        "scanned": len(files),
        "tagged": len(tagged),
        "missing": len(missing),
        "missing_paths": [m["path"] for m in missing if "path" in m],
        "tagged_sample": tagged[:40],
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Domain tag lint — latest",
        "",
        f"**Generated:** {now}  ",
        f"**Vault:** `{VAULT}`  ",
        f"**Scanned (hot paths):** {len(files)}  ",
        f"**With domain tag:** {len(tagged)}  ",
        f"**Missing domain tag:** {len(missing)}  ",
        "",
        "## Purpose",
        "Non-destructive coverage check for `#domain/*` / YAML `domain/*` on second-brain hot paths.",
        "Playbook: [[Setup/Obsidian-Category-Colors-and-Tags]]",
        "",
        "## Missing (action list)",
        "",
    ]
    if not missing:
        lines.append("_None — hot paths covered._")
    else:
        for m in missing[:200]:
            lines.append(f"- `{m['path']}`")
        if len(missing) > 200:
            lines.append(f"- … +{len(missing) - 200} more")
    lines += [
        "",
        "## Tagged sample",
        "",
    ]
    for t in tagged[:30]:
        lines.append(f"- `{t}`")
    lines += [
        "",
        "## How to run",
        "```bash",
        "python D:\\\\HermesData\\\\scripts\\\\vault_domain_tag_lint.py",
        "```",
        "",
        "## Vault links",
        "- [[Setup/Obsidian-Category-Colors-and-Tags]]",
        "- [[Operations/Second-Brain-Tools-Infra-Thread-2026-07-18]]",
        "- [[Housekeeping]]",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    summary = f"domain_tag_lint scanned={len(files)} tagged={len(tagged)} missing={len(missing)}"
    print(summary)
    if args.json:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
