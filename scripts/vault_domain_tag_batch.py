#!/usr/bin/env python3
"""Batch-add Phronesis domain tags to hot-path markdown (reversible).

Rules:
- Only files missing domain/* tags
- Folder → domain mapping (conservative)
- Optional type/canon|index from filename
- Never touches Archive, Roleplay-Sandbox, logs, .obsidian
- Writes manifest for undo

Usage:
  python vault_domain_tag_batch.py --dry-run
  python vault_domain_tag_batch.py --apply
  python vault_domain_tag_batch.py --undo MANIFEST.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

VAULT = Path(r"D:\PhronesisVault")
LOG_DIR = VAULT / "Operations" / "logs"
BACKUP_ROOT = VAULT / "Operations" / "backups" / "domain-tag-batch"

# (path_prefix_posix, domain_tags)
FOLDER_RULES: list[tuple[str, list[str]]] = [
    ("Research/Silo-Entities", ["domain/silo", "domain/twin"]),
    ("Digital-Twin", ["domain/twin"]),
    ("Operations", ["domain/ops"]),
    ("Setup", ["domain/setup"]),
    ("Research", ["domain/research"]),
    ("MOCs", ["domain/setup"]),
    ("Guides", ["domain/setup"]),
    ("Templates", ["domain/setup"]),
    ("Bases", ["domain/setup"]),
    ("Dashboard", ["domain/setup"]),
    ("Agents", ["domain/agents"]),
    ("WisdomKeeper", ["domain/wisdom"]),
    ("Vision", ["domain/wisdom"]),
    ("SkillForge", ["domain/wisdom"]),
    ("AI-Zone", ["domain/ai"]),
    ("Integrations", ["domain/ai"]),
    ("Discord", ["domain/discord"]),
    ("Discord-Channel-Infra", ["domain/discord"]),
    ("Discord-Servers", ["domain/discord"]),
    ("Housekeeping", ["domain/health"]),
    ("Resilience", ["domain/health"]),
    ("Incidents", ["domain/danger"]),
    ("Diagnostics", ["domain/danger"]),
    ("Security", ["domain/security"]),
    ("Revenue", ["domain/revenue"]),
    ("docs", ["domain/research"]),
]

ROOT_FILES = {
    "Housekeeping.md": ["domain/health", "domain/ops"],
    "00-INDEX.md": ["domain/setup", "type/index"],
    "AGENTS.md": ["domain/ops", "domain/agents"],
    "INDEX.md": ["domain/setup", "type/index"],
}

SKIP_SUBSTR = (
    "/logs/",
    "\\logs\\",
    "/archive/",
    "\\archive\\",
    "Distillations-",
    ".obsidian",
    "Roleplay-Sandbox",
    "/temp/",
    "\\temp\\",
    "copilot/",
    "node_modules",
    "/.git/",
    "\\venv\\",
    "/venv/",
    "replika-export-tool",
)

DOMAIN_SIMPLE = re.compile(r"domain/[\w-]+", re.I)
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.S)


def rel_posix(p: Path) -> str:
    return str(p.relative_to(VAULT)).replace("\\", "/")


def should_skip(p: Path) -> bool:
    s = str(p)
    return any(x in s for x in SKIP_SUBSTR)


def domains_for(p: Path) -> list[str]:
    rel = rel_posix(p)
    if rel in ROOT_FILES:
        return list(ROOT_FILES[rel])
    best: list[str] | None = None
    best_len = -1
    for prefix, tags in FOLDER_RULES:
        if rel == prefix or rel.startswith(prefix + "/"):
            if len(prefix) > best_len:
                best = list(tags)
                best_len = len(prefix)
    if best is None:
        return []
    name = p.name
    if "CANONICAL" in name.upper() or name.upper().endswith("-CANONICAL.MD"):
        if "type/canon" not in best:
            best.append("type/canon")
    if name in ("00-INDEX.md", "INDEX.md") or name.endswith("/00-INDEX.md"):
        if "type/index" not in best:
            best.append("type/index")
    if name == "00-INDEX.md" or name == "INDEX.md":
        if "type/index" not in best:
            best.append("type/index")
    return best


def has_domain(text: str) -> bool:
    if re.search(r"#domain/[\w-]+", text):
        return True
    m = FM_RE.match(text)
    if m and "domain/" in m.group(1):
        return True
    if re.search(r"(?m)^\s*-\s*domain/[\w-]+\s*$", text):
        return True
    if re.search(r"(?m)^tags:\s*\[[^\]]*domain/", text):
        return True
    return False


def parse_tags_from_fm(fm: str) -> list[str]:
    tags: list[str] = []
    tm = re.search(r"(?m)^tags:\s*\n((?:[ \t]*-[ \t]*.+\n)*)", fm)
    inline = re.search(r"(?m)^tags:\s*\[(.*?)\]\s*$", fm)
    if tm:
        tags = [t.strip().strip("'\"") for t in re.findall(r"-\s*[\"']?([^\"'\n#]+)", tm.group(1)) if t.strip()]
    elif inline:
        tags = [t.strip().strip("'\"") for t in inline.group(1).split(",") if t.strip()]
    return tags


def merge_frontmatter(text: str, add_tags: list[str]) -> tuple[str, list[str]]:
    """Return new text and list of tags actually added."""
    m = FM_RE.match(text)
    added: list[str] = []
    if not m:
        # prepend
        for t in add_tags:
            added.append(t)
        fm = "---\ntags:\n" + "\n".join(f"  - {t}" for t in add_tags) + "\n---\n\n"
        return fm + text, added

    fm = m.group(1)
    body = text[m.end() :]
    tags = parse_tags_from_fm(fm)
    for t in add_tags:
        if t not in tags:
            tags.append(t)
            added.append(t)
    if not added:
        return text, []

    fm2 = re.sub(r"(?m)^tags:\s*\n(?:[ \t]*-[ \t]*.+\n)*", "", fm)
    fm2 = re.sub(r"(?m)^tags:\s*\[.*?\]\s*\n?", "", fm2)
    tag_block = "tags:\n" + "\n".join(f"  - {t}" for t in tags) + "\n"
    if re.search(r"(?m)^title:", fm2):
        fm2 = re.sub(r"(?m)^(title:.*\n)", r"\1" + tag_block, fm2, count=1)
    else:
        fm2 = tag_block + fm2.lstrip("\n")
    return f"---\n{fm2.strip()}\n---\n{body}", added


def iter_candidates() -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    globs = [
        "Operations/*.md",
        "Setup/*.md",
        "Setup/**/*.md",
        "Research/*.md",
        "Research/Silo-Entities/*.md",
        "Digital-Twin/*.md",
        "Digital-Twin/**/*.md",
        "MOCs/*.md",
        "Guides/*.md",
        "Templates/*.md",
        "Dashboard/*.md",
        "Agents/*.md",
        "Housekeeping.md",
        "00-INDEX.md",
        "AGENTS.md",
        "INDEX.md",
    ]
    for g in globs:
        for p in VAULT.glob(g):
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            if should_skip(p):
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
    return sorted(out, key=lambda x: str(x).lower())


def cmd_dry_or_apply(apply: bool) -> int:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidates = iter_candidates()
    plan = []
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            plan.append({"path": rel_posix(p), "error": str(e)})
            continue
        if has_domain(text):
            continue
        want = domains_for(p)
        if not want:
            continue
        # simulate
        _, added = merge_frontmatter(text, want)
        if not added:
            continue
        plan.append({"path": rel_posix(p), "add": added})

    report = {
        "ts": ts,
        "mode": "apply" if apply else "dry-run",
        "candidates_scanned": len(candidates),
        "would_change": len([x for x in plan if "add" in x]),
        "items": plan,
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    dry_path = LOG_DIR / f"domain-tag-batch-{'apply' if apply else 'dry'}-{ts}.json"
    if atomic_write_json is not None:
        atomic_write_json(dry_path, report, indent=2, min_bytes=20)
        latest = LOG_DIR / "domain-tag-batch-latest.json"
        atomic_write_json(latest, report, indent=2, min_bytes=20)
    else:
        dry_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        latest = LOG_DIR / "domain-tag-batch-latest.json"
        latest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        f"# Domain tag batch — {'APPLY' if apply else 'DRY-RUN'}",
        "",
        f"**TS:** {ts}",
        f"**Scanned:** {len(candidates)}",
        f"**Changes:** {report['would_change']}",
        "",
        "## Plan",
        "",
    ]
    for it in plan[:300]:
        if "error" in it:
            md_lines.append(f"- ERROR `{it['path']}`: {it['error']}")
        else:
            md_lines.append(f"- `{it['path']}` ← `{', '.join(it['add'])}`")
    if len(plan) > 300:
        md_lines.append(f"- … +{len(plan)-300} more")
    md_lines += [
        "",
        "## Undo",
        "```bash",
        f"python D:\\\\HermesData\\\\scripts\\\\vault_domain_tag_batch.py --undo <manifest>",
        "```",
        "",
        "## Vault links",
        "- [[Setup/Obsidian-Category-Colors-and-Tags]]",
        "- [[Operations/logs/domain-tag-lint-latest]]",
        "",
    ]
    md_body = "\n".join(md_lines)
    md_path = LOG_DIR / "domain-tag-batch-latest.md"
    if atomic_write_text is not None:
        atomic_write_text(md_path, md_body, min_bytes=20)
    else:
        md_path.write_text(md_body, encoding="utf-8")

    print(f"mode={'apply' if apply else 'dry-run'} scanned={len(candidates)} changes={report['would_change']} report={dry_path}")

    if not apply:
        return 0

    # APPLY with backups + manifest
    batch_dir = BACKUP_ROOT / ts
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "ts": ts,
        "backup_dir": str(batch_dir),
        "files": [],
    }
    changed = 0
    errors = 0
    for it in plan:
        if "add" not in it:
            continue
        p = VAULT / it["path"]
        try:
            original = p.read_text(encoding="utf-8", errors="replace")
            # backup
            bdest = batch_dir / it["path"]
            bdest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, bdest)
            new_text, added = merge_frontmatter(original, it["add"])
            if not added:
                continue
            p.write_text(new_text, encoding="utf-8", newline="\n")
            manifest["files"].append({
                "path": it["path"],
                "added": added,
                "backup": str(bdest.relative_to(batch_dir)).replace("\\", "/"),
            })
            changed += 1
        except Exception as e:
            errors += 1
            manifest.setdefault("errors", []).append({"path": it["path"], "error": str(e)})

    man_path = LOG_DIR / f"domain-tag-batch-manifest-{ts}.json"
    if atomic_write_json is not None:
        atomic_write_json(man_path, manifest, indent=2, min_bytes=20)
        atomic_write_json(LOG_DIR / "domain-tag-batch-manifest-latest.json", manifest, indent=2, min_bytes=20)
    else:
        man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (LOG_DIR / "domain-tag-batch-manifest-latest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    print(f"applied={changed} errors={errors} manifest={man_path} backup={batch_dir}")
    return 0 if errors == 0 else 1


def cmd_undo(manifest_path: Path) -> int:
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    bdir = Path(man["backup_dir"])
    if not bdir.is_dir():
        print("BACKUP_MISSING", bdir)
        return 2
    restored = 0
    for f in man.get("files", []):
        src = bdir / f["backup"]
        dst = VAULT / f["path"]
        if not src.is_file():
            print("MISS_BACKUP", src)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored += 1
    print(f"undo_restored={restored} from={manifest_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--undo", type=str, default=None)
    args = ap.parse_args()
    if not VAULT.is_dir():
        print("VAULT_MISSING", file=sys.stderr)
        return 2
    if args.undo:
        return cmd_undo(Path(args.undo))
    return cmd_dry_or_apply(apply=bool(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
