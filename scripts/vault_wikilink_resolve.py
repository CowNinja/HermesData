#!/usr/bin/env python3
"""Shared Obsidian wikilink target resolution for living-scan + repair.

Design notes (research 2026-07-19):
- Obsidian help: folder paths are vault-root absolute with `/`; bare names use
  shortest/unique resolution across the vault (intentional, not cwd-relative).
- Explicit `./` and `../` ARE source-relative (forum + WhiteNoise). Markdown
  generators emit `../A.md` for parent folders.
- Pitfalls: bare-stem collisions (SKILL.md), wrong-depth `../../` after moves,
  treating absolute `K:/` / `D:/` as vault notes, and scanners that ignore
  source context so valid relative links look broken.
- Best practice for durable vault CNS: prefer shortest or vault-absolute
  wikilinks over fragile multi-hop `../` chains; rewrite when depth drifts.

Sources:
- https://help.obsidian.md/Linking+notes+and+files/Internal+links
- https://forum.obsidian.md/t/absolute-link-path-has-higher-precedence-than-relative-path/69542
- https://www.obsibrain.com/blog/obsidian-linking-the-complete-guide-to-connecting-your-notes
"""
from __future__ import annotations

import re
from pathlib import Path

LINK_EXTS = (".md", ".base", ".canvas", ".json")
JUNK_PARTS = {
    ".obsidian",
    "site-packages",
    "node_modules",
    "alice_venv",
    "__pycache__",
}


def norm_slash(s: str) -> str:
    return s.replace("\\", "/").strip()


def strip_md_ext(s: str) -> str:
    s = s.rstrip("/")
    if s.lower().endswith(".md"):
        return s[:-3]
    return s


def is_external_abs(t: str) -> bool:
    t = norm_slash(t)
    if t.startswith("http://") or t.startswith("https://"):
        return True
    if re.match(r"^[A-Za-z]:/", t) or t.startswith("//"):
        return True
    return False


def is_source_relative(t: str) -> bool:
    t = norm_slash(t)
    return t.startswith("../") or t.startswith("./") or t == ".." or t == "."


def vault_rel(path: Path, vault: Path) -> str | None:
    try:
        return norm_slash(str(path.resolve().relative_to(vault.resolve())))
    except (ValueError, OSError):
        return None


def under_vault(path: Path, vault: Path) -> bool:
    try:
        rp = path.resolve()
        rv = vault.resolve()
        return rp == rv or rv in rp.parents
    except OSError:
        return False


def physical_candidates(base: Path) -> list[Path]:
    """Expand a path (with or without extension) to checkable file paths."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)

    add(base)
    s = str(base)
    low = s.lower()
    has_known_ext = any(low.endswith(ext) for ext in LINK_EXTS)
    if has_known_ext:
        # also try stem without ext for folders/index edge cases
        add(Path(s[: -len(Path(s).suffix)]))
    else:
        for ext in LINK_EXTS:
            add(Path(s + ext))
    return out


def resolve_relative_to_source(target: str, source: Path, vault: Path) -> list[Path]:
    """Resolve ./ and ../ targets against the source note's parent directory."""
    t = norm_slash(target)
    try:
        # Pure path join + resolve (non-strict) mirrors Obsidian FS walk
        joined = (source.parent / t)
        resolved = joined.resolve()
    except OSError:
        return []
    return physical_candidates(resolved)


def path_exists_clean(path: Path, vault: Path) -> bool:
    try:
        if not path.exists():
            return False
        if not under_vault(path, vault):
            return False
        if any(x in path.parts for x in JUNK_PARTS):
            return False
        return True
    except OSError:
        return False


def target_hits_index(
    target: str,
    living_stems: set[str],
    living_paths: set[str],
    *,
    allow_bare_stem: bool = True,
) -> bool:
    """Index hit: vault-relative path keys and optional bare-stem (no slash)."""
    t = strip_md_ext(norm_slash(target))
    if not t:
        return True
    if t in living_paths or t.lower() in living_paths:
        return True
    # path with original ext already in index
    raw = norm_slash(target)
    if raw in living_paths or raw.lower() in living_paths:
        return True
    if allow_bare_stem and "/" not in t and not t.startswith("."):
        name = Path(t).name
        stem = name
        for ext in LINK_EXTS:
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        if stem in living_stems or stem.lower() in living_stems:
            return True
        if name in living_stems or name.lower() in living_stems:
            return True
    return False


def wikilink_exists(
    target: str,
    vault: Path,
    living_stems: set[str],
    living_paths: set[str],
    source: Path | None = None,
    *,
    extra_phys: list[Path] | None = None,
) -> bool:
    """True if target is skippable external URL, resolves as file, or hits index.

    Absolute drive paths (K:/, D:/) are NOT vault notes → False (callers may
    redirect them). HTTP(S) → True (not a vault defect).
    """
    t = norm_slash(target)
    if not t:
        return True
    if t.startswith("http://") or t.startswith("https://"):
        return True
    # Drive / UNC paths are external — do not pretend they are vault notes
    if re.match(r"^[A-Za-z]:/", t) or t.startswith("//"):
        return False

    # 1) Explicit source-relative
    if source is not None and is_source_relative(t):
        for cand in resolve_relative_to_source(t, source, vault):
            if path_exists_clean(cand, vault):
                return True
        # Also accept if the resolved vault-rel path is in the living index
        try:
            resolved = (source.parent / t).resolve()
            rel = vault_rel(resolved, vault)
            if rel:
                rel0 = strip_md_ext(rel)
                if rel0 in living_paths or rel0.lower() in living_paths:
                    return True
                if rel in living_paths or rel.lower() in living_paths:
                    return True
        except OSError:
            pass
        # Relative that does not resolve is unresolved (do NOT bare-stem
        # `../foo` — that masked broken depth in SkillForge practice logs)
        return False

    # 2) Index / bare-stem (path-free names only inside target_hits_index)
    if target_hits_index(t, living_stems, living_paths, allow_bare_stem=True):
        return True

    # 3) Physical candidates from vault root + optional hub folders
    ts = strip_md_ext(t)
    name = Path(ts).name
    phys: list[Path] = []
    for key in (ts, t):
        phys.extend(physical_candidates(vault / key))
    phys.extend(
        [
            vault / "Operations" / f"{name}.md",
            vault / "references" / f"{name}.md",
            vault / "docs" / "agent-coordination" / f"{name}.md",
            vault / "Bases" / f"{name}.md",
            vault / "Bases" / f"{name}.base",
            vault / "Digital-Twin" / f"{name}.md",
            vault / "Research" / f"{name}.md",
            vault / "SkillForge" / f"{name}.md",
        ]
    )
    if extra_phys:
        phys.extend(extra_phys)
    for c in phys:
        if path_exists_clean(c, vault):
            return True
    return False


def rewrite_relative_to_vault_abs(
    target: str,
    source: Path,
    vault: Path,
) -> str | None:
    """If relative target exists, return vault-absolute wikilink path (no .md).

    Used by residual clearance to replace fragile ../ chains with durable paths.
    """
    t = norm_slash(target)
    if not is_source_relative(t):
        return None
    for cand in resolve_relative_to_source(t, source, vault):
        if not path_exists_clean(cand, vault):
            continue
        rel = vault_rel(cand, vault)
        if not rel:
            continue
        return strip_md_ext(rel)
    return None
