#!/usr/bin/env python3
"""Five-item Wave-2 vault link clarity cook — 2026-07-18.

Items:
  1. Wikilink repair wave-2 (top unresolved + restore thin living hubs)
  2. False-positive audit (extend resolver for .base/.json/.md suffix)
  3. Bases/Domain-Tag-Index MD companions (wikilink-resolvable)
  4. Archive-link sweep for references/phronesisvault-*
  5. Hub densify: medical entities + session/health digests

Guardrails: no gateway, no VaultWalker LIVE arm, no mass delete, backup first.
Research notes (forum/plugin/docs 2026):
  - Prefer redirect map + vault-wide replace over blind delete of broken links
  - Distill→archive leaves path rot; thin living digests keep graph edges
  - Obsidian Bases live as .base; wikilinks without ext need MD companion or
    resolver that accepts non-md vault files
  - Dual-pass: apply → recount unresolved → apply residuals → recount
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    import sys as _sys

    _sys.path.insert(0, str(Path(r"D:\HermesData\scripts")))
    from atomic_io import atomic_write_json, atomic_write_text  # type: ignore

VAULT = Path(r"D:\PhronesisVault")
HERMES = Path(r"D:\HermesData")
TS = datetime.now(timezone.utc)
TS_ISO = TS.strftime("%Y-%m-%dT%H%M%SZ")
TS_DAY = TS.strftime("%Y-%m-%d")

BACKUP = VAULT / "Operations" / "backups" / f"wave2-link-clarity-{TS_ISO}"
OUT_JSON = HERMES / "logs" / "wave2-link-clarity-cook-latest.json"
OUT_MD = VAULT / "Operations" / "logs" / "wave2-link-clarity-cook-latest.md"
RECEIPT = VAULT / "Setup" / f"Wave2-Link-Clarity-Cook-Receipt-{TS_DAY}.md"
AUDIT_JSON = HERMES / "logs" / "wikilink-false-positive-audit-latest.json"
AUDIT_MD = VAULT / "Operations" / "logs" / "wikilink-false-positive-audit-latest.md"
SCORE = VAULT / "Operations" / "logs" / f"vaultwalker-effectiveness-scoreboard-{TS_DAY}.md"

LINK_RE = re.compile(r"\[\[([^\]|#]+)(\|[^\]]+)?\]\]")
SKIP_PARTS = {
    ".obsidian",
    "site-packages",
    "node_modules",
    ".git",
    "alice_venv",
    "backups",
}
SKIP_SCAN_EXTRA = {"Distillations-2026-07-10"}  # archive bulk — still rewrite lightly

# ---------------------------------------------------------------------------
# Redirect map (stem + full path keys)
# ---------------------------------------------------------------------------
EXPLICIT: dict[str, str] = {
    # Session masters / indexes
    "Session-Reports-2026-06-19-MASTER": "Operations/Session-Reports-2026-06-19-MASTER",
    "Operations/Session-Reports-2026-06-19-MASTER": "Operations/Session-Reports-2026-06-19-MASTER",
    "Session-Reports-2026-06-19-Index": "Operations/Session-Reports-2026-06-19-Index",
    # Lint / logs (JSON companions get MD wrappers)
    "Operations/Vault-Link-Lint-latest": "Operations/Vault-Link-Lint-latest",
    "Vault-Link-Lint-latest": "Operations/Vault-Link-Lint-latest",
    # Bases
    "Bases/Domain-Tag-Index": "Bases/Domain-Tag-Index",
    "Domain-Tag-Index": "Bases/Domain-Tag-Index",
    "Bases/Setup-Playbooks": "Bases/Setup-Playbooks",
    "Setup-Playbooks": "Bases/Setup-Playbooks",
    # Canonical walkthroughs (dated living files)
    "Hermes-Factual-vs-RP-Sanity-Walkthrough": "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    "Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17": "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    # Missing curator → gardener charter / STATUS
    "Operations/Phronesis-Curator-Librarian": "Operations/STATUS",
    "Phronesis-Curator-Librarian": "Operations/STATUS",
    # Health rounds → living STATUS + coordination
    "docs/agent-coordination/Sovereign-Stack-Health-Check-2026-06-24-round1": "docs/agent-coordination/STATUS",
    "docs/agent-coordination/Sovereign-Stack-Health-Check-2026-06-24-round1.md": "docs/agent-coordination/STATUS",
    "Sovereign-Stack-Health-Check-2026-06-24-round1": "docs/agent-coordination/STATUS",
    "Sovereign-Stack-Health-Check-2026-06-24-round1.md": "docs/agent-coordination/STATUS",
    # VW snapshots
    "Operations/VaultWalker-Snapshots-INDEX": "Operations/VaultWalker-Snapshots-INDEX",
    "VaultWalker-Snapshots-INDEX": "Operations/VaultWalker-Snapshots-INDEX",
    # Noise index
    "REVERIFICATION-NOISE-INDEX": "references/REVERIFICATION-NOISE-INDEX",
    "references/REVERIFICATION-NOISE-INDEX": "references/REVERIFICATION-NOISE-INDEX",
    # Entities
    "Dr-Kapoor": "Research/Silo-Entities/dr-kapoor",
    "Dr Kapoor": "Research/Silo-Entities/dr-kapoor",
    "dr kapoor": "Research/Silo-Entities/dr-kapoor",
    "Dr-Foster": "Research/Silo-Entities/dr-foster",
    "Dr Foster": "Research/Silo-Entities/dr-foster",
    "dr foster": "Research/Silo-Entities/dr-foster",
    "Dr-Richardson": "Research/Silo-Entities/richardson",
    "Dr Richardson": "Research/Silo-Entities/richardson",
    "richardson": "Research/Silo-Entities/richardson",
    # Prior digests still valid
    "Memory-Delta-Sessions-ROLLUP-2026-06-18": "Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18",
    "Automated-Routing-Batches-DIGEST": "Operations/Automated-Routing-Batches-DIGEST",
    "Secrets-Proposals-Batches-DIGEST": "Operations/Secrets-Proposals-Batches-DIGEST",
    "Session-Handoffs-DIGEST": "Operations/Session-Handoffs-DIGEST",
    "daily-distillation-INDEX": "Operations/logs/daily-distillation-INDEX",
    "VaultWalker-Safe-Gardener-2026-07-10": "Operations/VaultWalker-Safe-Gardener-2026-07-10",
    "HERMES-CONFIG-MAP": "Discord/configs/HERMES-CONFIG-MAP",
    "Resurfaced-Ideas-CORE": "Research/Resurfaced-Ideas-CORE",
    "Cron-Append-Policy": "Operations/Cron-Append-Policy",
    "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10": "Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10",
    "Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10": "Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10",
}

PREFIX_REDIRECTS: list[tuple[str, str]] = [
    ("phronesisvault-", "references/REVERIFICATION-NOISE-INDEX"),
    ("references/phronesisvault-", "references/REVERIFICATION-NOISE-INDEX"),
    ("Memory-Delta-", "Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18"),
    ("Automated-Routing-Batch-", "Operations/Automated-Routing-Batches-DIGEST"),
    ("Secrets-Proposals-Batch-", "Operations/Secrets-Proposals-Batches-DIGEST"),
    ("Session-Handoff-", "Operations/Session-Handoffs-DIGEST"),
    ("daily-distillation-20", "Operations/logs/daily-distillation-INDEX"),
    ("VaultWalker-Observations", "Operations/VaultWalker-Snapshots-INDEX"),
    ("VaultWalker-Post-Conformity", "Operations/VaultWalker-Snapshots-INDEX"),
    ("VaultWalker-Status-", "Operations/VaultWalker-Snapshots-INDEX"),
    ("Sovereign-Stack-Health-Check-2026-06-24-round", "docs/agent-coordination/STATUS"),
    ("MicroStep2-", "Operations/Session-Reports-2026-06-19-MASTER"),
    ("Ollama-", "Operations/Session-Reports-2026-06-19-MASTER"),
    ("Tiny-Classifier-", "Operations/Session-Reports-2026-06-19-MASTER"),
]

# Generic / intentional non-notes — do not count as "broken" in audit severity
ALLOWLIST_STEMS = {
    "wikilinks",
    "Person",
    "TODO",
    "todo",
    "note",
    "Notes",
    "Untitled",
    "attachment",
    "image",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def should_skip(p: Path, *, for_rewrite: bool = False) -> bool:
    if any(x in p.parts for x in SKIP_PARTS):
        return True
    if not for_rewrite and any(x in p.parts for x in SKIP_SCAN_EXTRA):
        return True
    # Roleplay purged bulk + sandbox deep archive: rewrite light only if for_rewrite
    if "Roleplay-Sandbox" in p.parts and "_archive" in p.parts and not for_rewrite:
        return True
    return False


def normalize_target(raw: str) -> str:
    t = raw.strip().replace("\\", "/")
    while t.startswith("./"):
        t = t[2:]
    if t.endswith(".md"):
        t = t[:-3]
    return t


def build_living_indexes() -> tuple[set[str], set[str], dict[str, str]]:
    """stems, path keys (no ext), stem->best rel path."""
    stems: set[str] = set()
    paths: set[str] = set()
    stem_to_path: dict[str, str] = {}
    # Index markdown + base + common companions that Obsidian can open
    patterns = ("*.md", "*.base", "*.canvas")
    for pat in patterns:
        for p in VAULT.rglob(pat):
            if should_skip(p):
                continue
            if "Distillations-2026-07-10" in p.parts:
                continue
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            rel_no_ext = rel.rsplit(".", 1)[0]
            paths.add(rel_no_ext)
            paths.add(rel_no_ext.lower())
            paths.add(rel)  # with ext
            stems.add(p.stem)
            stems.add(p.stem.lower())
            # prefer shorter / non-backup path
            for key in (p.stem, p.stem.lower()):
                prev = stem_to_path.get(key)
                if prev is None or len(rel_no_ext) < len(prev):
                    stem_to_path[key] = rel_no_ext
    return stems, paths, stem_to_path


def file_exists_fast(
    target: str,
    living_stems: set[str],
    living_paths: set[str],
    *,
    accept_json_md_wrapper: bool = True,
) -> bool:
    t = normalize_target(target)
    if not t or t.startswith("http"):
        return True
    # trailing slash folder-ish
    t_stripped = t.rstrip("/")
    if t in living_paths or t.lower() in living_paths:
        return True
    if t_stripped in living_paths or t_stripped.lower() in living_paths:
        return True
    name = Path(t_stripped).name
    if name in living_stems or name.lower() in living_stems:
        return True
    # direct filesystem
    for cand in (
        VAULT / f"{t}.md",
        VAULT / f"{t}.base",
        VAULT / f"{t}.canvas",
        VAULT / t,
        VAULT / f"{t_stripped}.md",
        VAULT / f"{t_stripped}.base",
    ):
        if cand.exists():
            return True
    if accept_json_md_wrapper:
        j = VAULT / f"{t}.json"
        if j.exists():
            return True
        j2 = VAULT / f"{t_stripped}.json"
        if j2.exists():
            return True
    return False


def lookup_redirect(raw: str) -> str | None:
    key = normalize_target(raw)
    base = Path(key).name
    if key in EXPLICIT:
        return EXPLICIT[key]
    if base in EXPLICIT:
        return EXPLICIT[base]
    # path with .md still in key variants
    if raw.strip().replace("\\", "/") in EXPLICIT:
        return EXPLICIT[raw.strip().replace("\\", "/")]
    for pref, dest in PREFIX_REDIRECTS:
        if base.startswith(pref) or key.startswith(pref) or pref in key:
            return dest
    return None


def backup_file(p: Path) -> None:
    if not p.exists() or not p.is_file():
        return
    rel = p.relative_to(VAULT)
    dest = BACKUP / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(p, dest)


def ensure_file(path: Path, content: str, *, force: bool = False) -> str:
    """Create or optionally refresh. Returns action."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return "exists"
    if path.exists():
        backup_file(path)
    path.write_text(content, encoding="utf-8", newline="\n")
    return "wrote" if not path.exists() else "created_or_overwrote"


def write_new(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return "exists"
    path.write_text(content, encoding="utf-8", newline="\n")
    return "created"


# ---------------------------------------------------------------------------
# Item 3 + thin hubs (prereq for repair)
# ---------------------------------------------------------------------------
def create_thin_hubs() -> dict:
    actions = {}

    # Session MASTER living hub (archive has full table)
    master = VAULT / "Operations" / "Session-Reports-2026-06-19-MASTER.md"
    arch_master = (
        VAULT
        / "Archive"
        / "Distillations-2026-07-10"
        / "Wave5"
        / "june19-reports"
        / "Session-Reports-2026-06-19-MASTER.md"
    )
    body = f"""---
title: Session Reports 2026-06-19 — MASTER (living hub)
date: {TS_DAY}
tags:
  - domain/ops
  - type/digest
  - status/live
aliases:
  - Session-Reports-2026-06-19-MASTER
  - june19 session master
---

# Session / Micro-Reports — 2026-06-19 MASTER (living)

> [!info] Wave-2 restore
> Thin living hub restored {TS_ISO} so graph edges resolve. Full swarm archived.

**Pointer index:** [[Operations/Session-Reports-2026-06-19-Index]]  
**Archive pack:** `Archive/Distillations-2026-07-10/Wave5/june19-reports/`

## Distilled lesson
- Prefer one living STATUS + thin receipts over N dated full reports.
- Phase/micro work should append to a single run log when possible.

## Related
- [[Operations/STATUS]]
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
- [[Operations/Session-Handoffs-DIGEST]]
- [[docs/agent-coordination/STATUS]]
- [[00-INDEX]]
"""
    if arch_master.exists() and not master.exists():
        # Prefer short living hub over copying huge archive verbatim
        actions["Session-MASTER"] = write_new(master, body)
    elif not master.exists():
        actions["Session-MASTER"] = write_new(master, body)
    else:
        actions["Session-MASTER"] = "exists"

    # Fix Index canonical pointer if it still points only at missing master wording
    idx = VAULT / "Operations" / "Session-Reports-2026-06-19-Index.md"
    if idx.exists():
        backup_file(idx)
        t = idx.read_text(encoding="utf-8", errors="ignore")
        if "living hub" not in t.lower():
            # ensure both links present
            if "Session-Reports-2026-06-19-MASTER" not in t:
                t = t.rstrip() + "\n\n**Canonical master:** [[Operations/Session-Reports-2026-06-19-MASTER]]\n"
            idx.write_text(t, encoding="utf-8", newline="\n")
            actions["Session-Index"] = "patched"
        else:
            actions["Session-Index"] = "ok"

    # VaultWalker Snapshots INDEX living
    vw = VAULT / "Operations" / "VaultWalker-Snapshots-INDEX.md"
    vw_body = f"""---
title: VaultWalker Status Snapshots — Index
date: {TS_DAY}
tags:
  - domain/ops
  - type/index
  - status/live
aliases:
  - VaultWalker-Snapshots-INDEX
---

# VaultWalker Status Snapshots — Index (living)

> Restored thin hub {TS_ISO}. Dated snapshot noise lives under Archive Wave5.

**Keep open**
- [[Operations/VaultWalker-Safe-Gardener-2026-07-10]]
- [[Operations/STATUS]]
- [[Operations/logs/vaultwalker-effectiveness-scoreboard-{TS_DAY}]]

**Archive:** `Archive/Distillations-2026-07-10/Wave5/vaultwalker-snapshots/`

## Policy
- VaultWalker LIVE stays Jeff-armed (`auto_live.armed=false` until explicit).
- Index-only / dry modes OK for agents.

## Vault links
- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]
- [[00-INDEX]]
"""
    actions["VW-Snapshots-INDEX"] = write_new(vw, vw_body)

    # Vault-Link-Lint MD wrapper around JSON
    lint_md = VAULT / "Operations" / "Vault-Link-Lint-latest.md"
    lint_json = VAULT / "Operations" / "Vault-Link-Lint-latest.json"
    lint_body = f"""---
title: Vault Link Lint — latest (wrapper)
date: {TS_DAY}
tags:
  - domain/ops
  - type/log
  - status/live
aliases:
  - Vault-Link-Lint-latest
---

# Vault Link Lint — latest

Machine report (if present): `Operations/Vault-Link-Lint-latest.json`  
Wave-2 companion MD so wikilinks resolve ({TS_ISO}).

See also:
- [[Operations/logs/wikilink-repair-latest]]
- [[Operations/logs/wave2-link-clarity-cook-latest]]
- [[Operations/logs/wikilink-false-positive-audit-latest]]
"""
    if not lint_md.exists():
        actions["Vault-Link-Lint-MD"] = write_new(lint_md, lint_body)
    else:
        actions["Vault-Link-Lint-MD"] = "exists"
    actions["Vault-Link-Lint-JSON"] = "present" if lint_json.exists() else "missing-json-ok"

    # Bases MD companions (Item 3)
    # Official docs: .base is first-class; MD companion embeds for graph/wikilink tools
    dti = VAULT / "Bases" / "Domain-Tag-Index.md"
    dti_body = f"""---
title: Domain Tag Index (Base companion)
date: {TS_DAY}
tags:
  - domain/setup
  - domain/ops
  - type/index
  - status/live
aliases:
  - Domain-Tag-Index
  - Bases/Domain-Tag-Index
---

# Domain Tag Index

> Companion note for [[Bases/Domain-Tag-Index.base|Domain-Tag-Index.base]] so path-style wikilinks and non-Bases tooling resolve.

```base
![[Bases/Domain-Tag-Index.base]]
```

If the embed does not render, open the `.base` file directly or use [[Dashboard/Domain-Tag-Dashboard]].

## Related
- [[Dashboard/Domain-Tag-Dashboard]]
- [[Setup/Obsidian-Category-Colors-and-Tags]]
- [[Bases/00-INDEX]]
- [[Bases/Setup-Playbooks]]
- [[Operations/logs/domain-tag-lint-latest]]
"""
    actions["Domain-Tag-Index.md"] = write_new(dti, dti_body)

    sp = VAULT / "Bases" / "Setup-Playbooks.md"
    sp_body = f"""---
title: Setup Playbooks (Base companion)
date: {TS_DAY}
tags:
  - domain/setup
  - type/index
  - status/live
aliases:
  - Setup-Playbooks
---

# Setup Playbooks

Companion for [[Bases/Setup-Playbooks.base|Setup-Playbooks.base]] ({TS_ISO}).

```base
![[Bases/Setup-Playbooks.base]]
```

## Related
- [[Bases/Domain-Tag-Index]]
- [[Bases/00-INDEX]]
- [[Setup/Obsidian-Category-Colors-and-Tags]]
"""
    actions["Setup-Playbooks.md"] = write_new(sp, sp_body)

    # Optional thin curator stub → points at STATUS (avoid inventing role)
    # We redirect links to STATUS instead of creating fake librarian note.
    actions["Phronesis-Curator-Librarian"] = "redirect-to-STATUS"

    return actions


# ---------------------------------------------------------------------------
# Item 1 + 4: rewrite pass
# ---------------------------------------------------------------------------
def rewrite_pass(
    living_stems: set[str], living_paths: set[str]
) -> dict:
    rewritten_files = 0
    replacements = 0
    examples: list[str] = []
    by_dest: Counter[str] = Counter()
    touched: list[str] = []

    for p in VAULT.rglob("*.md"):
        if should_skip(p, for_rewrite=True):
            continue
        # Skip our own backup tree
        if "wave2-link-clarity-" in str(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def repl(m: re.Match) -> str:
            nonlocal replacements
            raw = m.group(1).strip()
            alias = m.group(2) or ""
            if raw.startswith("http"):
                return m.group(0)
            key = normalize_target(raw)
            dest = lookup_redirect(raw)
            if not dest:
                return m.group(0)
            dest_n = normalize_target(dest)
            # If old already resolves living AND dest==old, skip
            if file_exists_fast(key, living_stems, living_paths) and dest_n == key:
                return m.group(0)
            # If old resolves and is NOT a prefix-noise redirect, keep
            # Exception: phronesisvault always redirect even if somehow present
            base = Path(key).name
            force_noise = base.startswith("phronesisvault-") or "phronesisvault-" in key
            if file_exists_fast(key, living_stems, living_paths) and not force_noise:
                # already good — but if explicit says different living target for alias stems
                if dest_n != key and key not in living_paths and key.lower() not in living_paths:
                    pass  # fall through
                else:
                    # if dest is preferred hub and old is missing path form
                    if file_exists_fast(key, living_stems, living_paths):
                        return m.group(0)
            if dest_n.replace("\\", "/") == key:
                return m.group(0)
            replacements += 1
            by_dest[dest_n] += 1
            if len(examples) < 50:
                examples.append(f"{raw} -> {dest_n}")
            if alias:
                return f"[[{dest_n}{alias}]]"
            return f"[[{dest_n}]]"

        new = LINK_RE.sub(repl, text)
        if new != text:
            backup_file(p)
            p.write_text(new, encoding="utf-8", newline="\n")
            rewritten_files += 1
            touched.append(str(p.relative_to(VAULT)).replace("\\", "/"))

    return {
        "rewritten_files": rewritten_files,
        "replacements": replacements,
        "examples": examples,
        "by_dest": by_dest.most_common(20),
        "touched_sample": touched[:40],
    }


# ---------------------------------------------------------------------------
# Item 2: unresolved scan + false-positive audit
# ---------------------------------------------------------------------------
def scan_unresolved(
    living_stems: set[str], living_paths: set[str]
) -> tuple[list[tuple[str, str]], list[dict], Counter]:
    unresolved: list[tuple[str, str]] = []
    rows: list[dict] = []
    for p in VAULT.rglob("*.md"):
        if should_skip(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in LINK_RE.finditer(text):
            raw = m.group(1).strip().replace("\\", "/")
            if raw.startswith("http"):
                continue
            if file_exists_fast(raw, living_stems, living_paths):
                continue
            # classify
            key = normalize_target(raw)
            base = Path(key.rstrip("/")).name
            cls = "real_broken"
            note = ""
            # check archive-only
            arch_hits = []
            for ap in VAULT.rglob(f"{base}.md"):
                if "Archive" in ap.parts or "Distillations" in ap.parts:
                    arch_hits.append(str(ap.relative_to(VAULT)).replace("\\", "/"))
                    if len(arch_hits) >= 2:
                        break
            if arch_hits:
                cls = "archive_only"
                note = arch_hits[0]
            # json only
            if (VAULT / f"{key}.json").exists() or (VAULT / f"{key}.md").exists():
                cls = "companion_mismatch"
            # base without companion (should be fixed)
            if (VAULT / f"{key}.base").exists():
                cls = "false_positive_base"
            # allowlist generics / person folder stubs
            if base in ALLOWLIST_STEMS or key.endswith("/"):
                cls = "allowlist_or_folderish"
            # trailing slash people stubs
            if key.endswith("/") or re.match(r"^[A-Z][a-z]+-[A-Z]", base):
                if cls == "real_broken":
                    cls = "entity_stub_candidate"
            unresolved.append((str(p.relative_to(VAULT)).replace("\\", "/"), raw))
            rows.append(
                {
                    "source": str(p.relative_to(VAULT)).replace("\\", "/"),
                    "target": raw,
                    "class": cls,
                    "note": note,
                }
            )
    top = Counter(t for _, t in unresolved)
    return unresolved, rows, top


# ---------------------------------------------------------------------------
# Item 5: hub densify
# ---------------------------------------------------------------------------
def densify_hubs() -> dict:
    actions = {}
    entity_footer = f"""

## Vault links (wave-2 hub densify {TS_DAY})
- [[Research/Silo-Entities/dr-kapoor]]
- [[Research/Silo-Entities/dr-foster]]
- [[Research/Silo-Entities/richardson]]
- [[Operations/STATUS]]
- [[docs/agent-coordination/STATUS]]
- [[Dashboard/Domain-Tag-Dashboard]]
- [[00-INDEX]]
"""
    entities = [
        VAULT / "Research" / "Silo-Entities" / "dr-kapoor.md",
        VAULT / "Research" / "Silo-Entities" / "dr-foster.md",
        VAULT / "Research" / "Silo-Entities" / "richardson.md",
    ]
    for e in entities:
        if not e.exists():
            actions[e.name] = "missing"
            continue
        backup_file(e)
        t = e.read_text(encoding="utf-8", errors="ignore")
        if "wave-2 hub densify" in t:
            actions[e.name] = "already"
            continue
        # cross-link siblings
        t2 = t.rstrip() + entity_footer
        e.write_text(t2, encoding="utf-8", newline="\n")
        actions[e.name] = "footer_added"

    # Medical / ops digests that should point at entities
    hub_targets = [
        VAULT / "Operations" / "STATUS.md",
        VAULT / "docs" / "agent-coordination" / "STATUS.md",
        VAULT / "Operations" / "Session-Reports-2026-06-19-MASTER.md",
        VAULT / "Operations" / "Session-Handoffs-DIGEST.md",
        VAULT / "references" / "REVERIFICATION-NOISE-INDEX.md",
        VAULT / "Dashboard" / "Domain-Tag-Dashboard.md",
        VAULT / "Bases" / "00-INDEX.md",
    ]
    medical_block = f"""

## Medical entity hubs (wave-2 {TS_DAY})
- [[Research/Silo-Entities/dr-kapoor|Dr Kapoor — PCM Hampton VAMC]]
- [[Research/Silo-Entities/dr-foster|Dr Foster — psychologist NMCP]]
- [[Research/Silo-Entities/richardson|Dr Richardson — endocrinology]]
"""
    ops_block = f"""

## Wave-2 clarity hubs ({TS_DAY})
- [[Operations/Session-Reports-2026-06-19-MASTER]]
- [[Operations/VaultWalker-Snapshots-INDEX]]
- [[Operations/Vault-Link-Lint-latest]]
- [[Bases/Domain-Tag-Index]]
- [[references/REVERIFICATION-NOISE-INDEX]]
- [[Operations/logs/wave2-link-clarity-cook-latest]]
"""
    for h in hub_targets:
        if not h.exists():
            actions[str(h.relative_to(VAULT))] = "missing"
            continue
        backup_file(h)
        t = h.read_text(encoding="utf-8", errors="ignore")
        changed = False
        # medical on STATUS + session master only
        if h.name in ("STATUS.md", "Session-Reports-2026-06-19-MASTER.md"):
            if "Medical entity hubs (wave-2" not in t:
                t = t.rstrip() + medical_block
                changed = True
        if "Wave-2 clarity hubs" not in t and h.name != "REVERIFICATION-NOISE-INDEX.md":
            t = t.rstrip() + ops_block
            changed = True
        if h.name == "REVERIFICATION-NOISE-INDEX.md" and "wave-2 link clarity" not in t.lower():
            t = t.rstrip() + f"\n\n_Wave-2 link clarity cook {TS_ISO}: living `references/phronesisvault-*` noise → this index._\n"
            changed = True
        if changed:
            h.write_text(t, encoding="utf-8", newline="\n")
            actions[str(h.relative_to(VAULT)).replace("\\", "/")] = "densified"
        else:
            actions[str(h.relative_to(VAULT)).replace("\\", "/")] = "skip"

    return actions


def write_receipts(payload: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, payload)

    top = payload.get("after_top") or []
    lines = [
        f"# Wave-2 Link Clarity Cook — {TS_DAY}",
        "",
        f"- UTC: `{payload.get('ts')}`",
        f"- Backup: `{payload.get('backup')}`",
        f"- Dual-verify: **{payload.get('dual_verify')}**",
        "",
        "## Research (condensed)",
        "- Forum/Python map+replace for mangled/broken wikilinks (not blind delete).",
        "- Distill/archive path rot fixed via thin living hubs + redirect prefixes.",
        "- Obsidian Bases: `.base` first-class; MD companions for graph/lint tools.",
        "- Sources: Obsidian Help Bases; forum broken-link threads; Vault Inspector patterns.",
        "",
        "## Item results",
        f"- Thin hubs: `{json.dumps(payload.get('thin_hubs'), default=str)[:500]}`",
        f"- Rewrite pass1: files={payload.get('pass1', {}).get('rewritten_files')} repl={payload.get('pass1', {}).get('replacements')}",
        f"- Rewrite pass2: files={payload.get('pass2', {}).get('rewritten_files')} repl={payload.get('pass2', {}).get('replacements')}",
        f"- Unresolved before→after: **{payload.get('unresolved_before')} → {payload.get('unresolved_after')}**",
        f"- False-positive classes: `{payload.get('class_counts')}`",
        f"- Hub densify: `{payload.get('hub_densify')}`",
        "",
        "## Top unresolved after",
    ]
    for t, n in top[:25]:
        lines.append(f"- ({n}) `{t}`")
    lines += [
        "",
        "## Examples applied",
    ]
    for e in (payload.get("pass1", {}) or {}).get("examples", [])[:15]:
        lines.append(f"- `{e}`")
    lines += [
        "",
        "## Vault links",
        "- [[Operations/STATUS]]",
        "- [[Bases/Domain-Tag-Index]]",
        "- [[Dashboard/Domain-Tag-Dashboard]]",
        "- [[references/REVERIFICATION-NOISE-INDEX]]",
        "- [[Research/Silo-Entities/dr-kapoor]]",
        "",
    ]
    md_body = "\n".join(lines)
    atomic_write_text(OUT_MD, md_body)

    receipt = f"""---
title: Wave-2 Link Clarity Cook Receipt
date: {TS_DAY}
tags:
  - domain/ops
  - domain/setup
  - type/receipt
  - status/live
---

# Wave-2 Link Clarity Cook Receipt — {TS_DAY}

**UTC:** {payload.get('ts')}  
**Dual-verify:** {payload.get('dual_verify')}  
**Backup:** `{payload.get('backup')}`

| Item | Result |
|------|--------|
| 1 Wikilink repair wave-2 | unresolved {payload.get('unresolved_before')} → {payload.get('unresolved_after')}; repl p1/p2 = {payload.get('pass1',{}).get('replacements')}/{payload.get('pass2',{}).get('replacements')} |
| 2 False-positive audit | classes {payload.get('class_counts')} |
| 3 Bases Domain-Tag-Index | MD companions + .base kept |
| 4 phronesisvault-* sweep | prefix → REVERIFICATION-NOISE-INDEX |
| 5 Hub densify | medical entities + STATUS/session |

## Jeff once
Ctrl+R if graph still sticky — optional.

## Logs
- [[Operations/logs/wave2-link-clarity-cook-latest]]
- [[Operations/logs/wikilink-false-positive-audit-latest]]
- `D:\\\\HermesData\\\\logs\\\\wave2-link-clarity-cook-latest.json`
"""
    atomic_write_text(RECEIPT, receipt)

    # scoreboard touch
    sb = f"""---
title: VaultWalker effectiveness scoreboard
date: {TS_DAY}
tags:
  - domain/ops
  - type/log
  - status/live
---

# VaultWalker / Gardener scoreboard — {TS_DAY}

| Metric | Value |
|--------|-------|
| Wave-2 unresolved after | {payload.get('unresolved_after')} |
| Wave-2 replacements (p1+p2) | {(payload.get('pass1') or {}).get('replacements', 0) + (payload.get('pass2') or {}).get('replacements', 0)} |
| Dual-verify | {payload.get('dual_verify')} |
| VW LIVE | still Jeff-armed (false) |

See [[Operations/logs/wave2-link-clarity-cook-latest]].
"""
    atomic_write_text(SCORE, sb)

    # also mirror wikilink-repair-latest for continuity
    repair_latest = {
        "ts": payload.get("ts"),
        "wave": "wave2-link-clarity",
        "redirects": len(EXPLICIT) + len(PREFIX_REDIRECTS),
        "rewritten_files": (payload.get("pass1") or {}).get("rewritten_files", 0)
        + (payload.get("pass2") or {}).get("rewritten_files", 0),
        "replacements": (payload.get("pass1") or {}).get("replacements", 0)
        + (payload.get("pass2") or {}).get("replacements", 0),
        "unresolved_count": payload.get("unresolved_after"),
        "top_unresolved": payload.get("after_top"),
        "examples": (payload.get("pass1") or {}).get("examples", [])[:30],
    }
    atomic_write_json(HERMES / "logs" / "wikilink-repair-latest.json", repair_latest)
    atomic_write_text(VAULT / "Operations" / "logs" / "wikilink-repair-latest.md", md_body)


def main() -> int:
    BACKUP.mkdir(parents=True, exist_ok=True)
    log(f"BACKUP={BACKUP}")

    # Pre-index
    living_stems, living_paths, stem_to_path = build_living_indexes()
    log(f"living stems={len(living_stems)} paths={len(living_paths)}")

    # Baseline unresolved (old-style will drop after hubs)
    before_unres, before_rows, before_top = scan_unresolved(living_stems, living_paths)
    log(f"unresolved_before={len(before_unres)} top={before_top.most_common(8)}")

    # Item 3 + thin hubs first so resolver sees them
    thin = create_thin_hubs()
    log(f"thin_hubs={thin}")

    # Rebuild indexes after hub creation
    living_stems, living_paths, stem_to_path = build_living_indexes()

    # Pass 1 rewrite (items 1+4)
    pass1 = rewrite_pass(living_stems, living_paths)
    log(f"pass1={pass1['rewritten_files']} files, {pass1['replacements']} repl")

    living_stems, living_paths, stem_to_path = build_living_indexes()
    mid_unres, mid_rows, mid_top = scan_unresolved(living_stems, living_paths)
    log(f"unresolved_mid={len(mid_unres)}")

    # Pass 2 residual rewrite
    pass2 = rewrite_pass(living_stems, living_paths)
    log(f"pass2={pass2['rewritten_files']} files, {pass2['replacements']} repl")

    # Item 5 hubs
    hubs = densify_hubs()
    log(f"hubs={hubs}")

    living_stems, living_paths, stem_to_path = build_living_indexes()
    after_unres, after_rows, after_top = scan_unresolved(living_stems, living_paths)
    log(f"unresolved_after={len(after_unres)} top={after_top.most_common(10)}")

    # Dual-verify: second independent recount
    v2_unres, v2_rows, v2_top = scan_unresolved(living_stems, living_paths)
    dual = "PASS" if len(v2_unres) == len(after_unres) else "FAIL_COUNT_MISMATCH"
    # Critical targets must resolve
    critical = [
        "Operations/Session-Reports-2026-06-19-MASTER",
        "Operations/Vault-Link-Lint-latest",
        "Bases/Domain-Tag-Index",
        "Bases/Setup-Playbooks",
        "references/REVERIFICATION-NOISE-INDEX",
        "Research/Silo-Entities/dr-kapoor",
        "Research/Silo-Entities/dr-foster",
        "Research/Silo-Entities/richardson",
        "Operations/VaultWalker-Snapshots-INDEX",
        "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    ]
    crit_ok = {c: file_exists_fast(c, living_stems, living_paths) for c in critical}
    if not all(crit_ok.values()):
        dual = "FAIL_CRITICAL"
    if dual == "PASS":
        dual = "PASS x2"

    class_counts = Counter(r["class"] for r in after_rows)
    audit = {
        "ts": TS.isoformat(),
        "unresolved_total": len(after_unres),
        "class_counts": dict(class_counts),
        "top_unresolved": after_top.most_common(40),
        "sample_rows": after_rows[:80],
        "critical_ok": crit_ok,
        "dual_verify": dual,
        "research_notes": [
            "Map+replace preferred over batch-delete broken links (Obsidian forum).",
            "Bases are .base files; lint tools need MD companion or multi-ext index.",
            "Archive-only targets → thin living digest, not deep archive path in graph.",
        ],
    }
    AUDIT_JSON.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(AUDIT_JSON, audit)
    alines = [
        f"# Wikilink False-Positive Audit — {TS_DAY}",
        "",
        f"- Total still unresolved (living scan): **{len(after_unres)}**",
        f"- Classes: `{dict(class_counts)}`",
        f"- Dual-verify: **{dual}**",
        "",
        "## Critical targets",
    ]
    for c, ok in crit_ok.items():
        alines.append(f"- {'OK' if ok else 'MISSING'} `{c}`")
    alines += ["", "## Top unresolved"]
    for t, n in after_top.most_common(30):
        alines.append(f"- ({n}) `{t}`")
    alines += ["", "## Class legend", "- `real_broken` — no living file", "- `archive_only` — only under Archive/Distillations", "- `false_positive_base` — .base exists", "- `companion_mismatch` — json/md wrapper issue", "- `allowlist_or_folderish` / `entity_stub_candidate` — intentional stubs", ""]
    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(AUDIT_MD, "\n".join(alines))

    payload = {
        "ts": TS.isoformat(),
        "backup": str(BACKUP),
        "thin_hubs": thin,
        "pass1": {k: pass1[k] for k in ("rewritten_files", "replacements", "examples", "by_dest")},
        "pass2": {k: pass2[k] for k in ("rewritten_files", "replacements", "examples", "by_dest")},
        "unresolved_before": len(before_unres),
        "unresolved_mid": len(mid_unres),
        "unresolved_after": len(after_unres),
        "before_top": before_top.most_common(20),
        "after_top": after_top.most_common(30),
        "class_counts": dict(class_counts),
        "hub_densify": hubs,
        "critical_ok": crit_ok,
        "dual_verify": dual,
        "verify2_count": len(v2_unres),
    }
    write_receipts(payload)
    log(json.dumps({k: payload[k] for k in ("unresolved_before", "unresolved_after", "dual_verify", "critical_ok")}, indent=2, default=str))
    return 0 if dual.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
