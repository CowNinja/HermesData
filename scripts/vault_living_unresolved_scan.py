#!/usr/bin/env python3
"""Living-only vault wikilink unresolved scan (truth surface for hygiene).

Excludes Archive / Alice / RP / backups / noise so daily hygiene stops
crying wolf on distill archives. Multi-ext resolve (.md/.base/.canvas/.json).

Usage:
  python D:\\HermesData\\scripts\\vault_living_unresolved_scan.py
  python D:\\HermesData\\scripts\\vault_living_unresolved_scan.py --json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OUT_JSON = Path(r"D:\HermesData\logs\living-unresolved-latest.json")
OUT_MD = VAULT / "Operations" / "logs" / "living-unresolved-latest.md"
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

SKIP_PARTS = {
    ".obsidian",
    "site-packages",
    "node_modules",
    ".git",
    "alice_venv",
    "__pycache__",
    "backups",
}
SKIP_PREFIXES = (
    "Archive/",
    "Alice/",
    "Roleplay-Sandbox/",
    "Operations/backups/",
    "Backups/",
    "references/",
    "tests/",
    "copilot/",
    ".smart-env/",
    "temp/",
    "temp_sources/",
    "scripts/",
    "Operations/logs/cron-append/",
    "Operations/logs/log-intelligence/",
    "docs/agent-coordination/incidents/",
    "AI-Zone/Drafts/",
    "AI-Zone/exports/",
    "Discord/configs/",
    "Operations/graphs/",
)


def relp(p: Path) -> str:
    return str(p.relative_to(VAULT)).replace("\\", "/")


def is_living(p: Path) -> bool:
    r = relp(p)
    if any(x in p.parts for x in SKIP_PARTS):
        return False
    if any(r.startswith(pref) for pref in SKIP_PREFIXES):
        return False
    return True


def build_indexes() -> tuple[set[str], set[str]]:
    stems: set[str] = set()
    paths: set[str] = set()
    for pat in ("*.md", "*.base", "*.canvas", "*.json"):
        for p in VAULT.rglob(pat):
            if not is_living(p):
                continue
            r = relp(p)
            r0 = r.rsplit(".", 1)[0]
            paths.add(r0)
            paths.add(r0.lower())
            paths.add(r)
            stems.add(p.stem)
            stems.add(p.stem.lower())
    return stems, paths


def exists(target: str, stems: set[str], paths: set[str], source: Path | None = None) -> bool:
    """Resolve if living index hits OR physical vault path exists.

    Outbound scan is living-only (no Archive noise). Targets may live under
    excluded folders (references/, Archive pointers) and still count as OK
    so we don't false-fail real digests / noise indexes.

    Bare-stem matching only for path-free simple note names — never for
    `skills/.../SKILL.md` style paths (stem collision).

    Relative targets (`../`, `./`) resolve against the source note parent.
    """
    t = target.strip().replace("\\", "/")
    if not t or t.startswith("http"):
        return True
    # External absolute paths are not Obsidian vault notes
    if re.match(r"^[A-Za-z]:[/\\]", t) or t.startswith("//"):
        return False

    # Relative path against source note
    candidates_rel: list[str] = []
    if source is not None and (t.startswith("../") or t.startswith("./") or t.startswith("..\\")):
        try:
            resolved = (source.parent / t).resolve()
            try:
                rrel = str(resolved.relative_to(VAULT.resolve())).replace("\\", "/")
                if rrel.endswith(".md"):
                    rrel = rrel[:-3]
                candidates_rel.append(rrel)
                # also try without resolve if still under vault as-is
            except ValueError:
                pass
            # physical
            for ext in (".md", ".base", ".canvas", ".json", ""):
                c = Path(str(resolved) + (ext if ext and not str(resolved).endswith(ext) else ""))
                if ext == "":
                    c = resolved
                if c.exists() and VAULT.resolve() in c.resolve().parents or (
                    c.exists() and c.resolve() == VAULT.resolve()
                ):
                    return True
                if (Path(str(resolved) + ".md")).exists():
                    return True
                if resolved.exists():
                    return True
                break
        except OSError:
            pass

    if t.endswith(".md"):
        t = t[:-3]
    ts = t.rstrip("/")
    check_keys = [ts] + candidates_rel
    for key in check_keys:
        k = key.rstrip("/")
        if k in paths or k.lower() in paths:
            return True
    # Simple name only (no /) — stem or path-key match
    if "/" not in ts and "\\" not in ts and not ts.startswith(".."):
        name = Path(ts).name
        # drop trailing .base/.canvas for simple match
        stem = name
        for ext in (".base", ".canvas", ".json"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
        if stem in stems or stem.lower() in stems:
            return True
        if name in stems or name.lower() in stems:
            return True
    # Physical existence anywhere under vault (skip only junk package trees)
    junk = {".obsidian", "site-packages", "node_modules", "alice_venv", "__pycache__"}
    name = Path(ts).name
    phys = []
    for key in check_keys:
        phys.extend(
            [
                VAULT / f"{key}.md",
                VAULT / f"{key}.base",
                VAULT / f"{key}.canvas",
                VAULT / f"{key}.json",
                VAULT / key,
            ]
        )
    phys.extend(
        [
            VAULT / f"{ts}.md",
            VAULT / f"{ts}.base",
            VAULT / f"{ts}.canvas",
            VAULT / f"{ts}.json",
            VAULT / ts,
            VAULT / "Operations" / f"{name}.md",
            VAULT / "references" / f"{name}.md",
            VAULT / "docs" / "agent-coordination" / f"{name}.md",
            VAULT / "Bases" / f"{name}.md",
            VAULT / "Bases" / f"{name}.base",
            VAULT / "Digital-Twin" / f"{name}.md",
        ]
    )
    for c in phys:
        try:
            if not c.exists():
                continue
            if any(x in c.parts for x in junk):
                continue
            return True
        except OSError:
            continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    stems, paths = build_indexes()
    unresolved: list[tuple[str, str]] = []
    scanned = 0
    for p in VAULT.rglob("*.md"):
        if not is_living(p):
            continue
        scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in LINK_RE.finditer(text):
            raw = m.group(1).strip().replace("\\", "/")
            if not exists(raw, stems, paths, source=p):
                unresolved.append((relp(p), raw))

    top = Counter(t for _, t in unresolved).most_common(40)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "living_md_scanned": scanned,
        "unresolved_link_count": len(unresolved),
        "unique_targets": len({t for _, t in unresolved}),
        "top_unresolved": top,
        "sample": unresolved[:40],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# Living Unresolved Scan — {payload['ts'][:10]}",
        "",
        f"- Living md scanned: **{scanned}**",
        f"- Unresolved links: **{len(unresolved)}**",
        f"- Unique targets: **{payload['unique_targets']}**",
        "",
        "## Top unresolved targets",
    ]
    for t, n in top[:30]:
        lines.append(f"- ({n}) `{t}`")
    lines += [
        "",
        "## Vault links",
        "- [[Operations/STATUS]]",
        "- [[Housekeeping]]",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2)[:8000])
    else:
        print(
            json.dumps(
                {
                    "living_md_scanned": scanned,
                    "unresolved_link_count": len(unresolved),
                    "unique_targets": payload["unique_targets"],
                    "top_unresolved": top[:15],
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
