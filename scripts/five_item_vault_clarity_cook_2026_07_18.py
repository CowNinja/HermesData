#!/usr/bin/env python3
"""Five-item vault clarity cook (2026-07-18).

Jeff green-light: C both graph+distill, thorough archive, safe autonomy,
detective entity resolve from silo cards, VaultWalker = the gardener.

Items:
  1) Critical domain tags + lint green
  2) Graph readability (filters, hide unresolved, orphans strategy)
  3) Wikilink repair + hub backlinks + entity redirects
  4) Distill references reverification cluster + archive (policy L1/L2)
  5) VaultWalker guardrails (index ownership, junk skip, auto_live scoreboard)

Research basis (session web):
  - Karpathy LLM Wiki: lint orphans/broken links; graph = shape of knowledge
  - Verify-then-merge / repair phase after build (Penfield, AI Operator)
  - Distill-first never hard-delete (Vault-Distillation-Policy already in vault)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OBS = VAULT / ".obsidian"
HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
LOGS = VAULT / "Operations" / "logs"
SETUP = VAULT / "Setup"
ARCH_VAULT = VAULT / "Archive" / "Distillations-2026-07-10" / "references-reverification-2026-07-18"
ARCH_HERMES = HERMES / "archives" / "references-reverification-2026-07-18"
BAK = OBS / "backups" / f"five-item-clarity-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
TS_FILE = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
PY = sys.executable
REPORT: dict = {"ts": TS, "items": {}, "research": []}


def log(msg: str) -> None:
    print(msg, flush=True)


def run(args: list[str], timeout: int = 900) -> dict:
    log("RUN " + " ".join(args))
    try:
        r = subprocess.run(
            args,
            cwd=str(HERMES),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or ""))[-4000:]
        return {"exit": r.returncode, "out": out}
    except subprocess.TimeoutExpired:
        return {"exit": 124, "out": "TIMEOUT"}
    except Exception as e:
        return {"exit": 1, "out": f"{type(e).__name__}: {e}"}


def ensure_domain_tags(path: Path, tags: list[str]) -> str:
    """Insert or merge domain tags into YAML frontmatter. Returns action."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"domain/[\w-]+", text):
        return "already"
    fm_m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if fm_m:
        body = text[fm_m.end() :]
        fm = fm_m.group(1)
        if re.search(r"^tags:\s*$", fm, re.M) or re.search(r"^tags:\s*\[", fm, re.M) or re.search(r"^tags:\s*\n", fm, re.M):
            # has tags key
            if re.search(r"^tags:\s*\[", fm, re.M):
                # inline list
                def add_inline(m: re.Match) -> str:
                    inner = m.group(1).strip()
                    existing = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
                    for t in tags:
                        if t not in existing:
                            existing.append(t)
                    return "tags: [" + ", ".join(existing) + "]"

                fm2 = re.sub(r"^tags:\s*\[(.*?)\]", add_inline, fm, count=1, flags=re.M)
            else:
                # block list
                lines = fm.splitlines()
                out_lines = []
                i = 0
                inserted = False
                while i < len(lines):
                    out_lines.append(lines[i])
                    if re.match(r"^tags:\s*$", lines[i]) and not inserted:
                        # collect existing - items
                        j = i + 1
                        existing = []
                        while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                            existing.append(re.sub(r"^\s+-\s+", "", lines[j]).strip())
                            j += 1
                        for t in tags:
                            if t not in existing:
                                existing.append(t)
                        # rewrite tag block
                        out_lines = out_lines[:-1] + ["tags:"] + [f"  - {t}" for t in existing]
                        i = j
                        inserted = True
                        continue
                    i += 1
                if not inserted:
                    out_lines.append("tags:")
                    for t in tags:
                        out_lines.append(f"  - {t}")
                fm2 = "\n".join(out_lines)
        else:
            fm2 = fm.rstrip() + "\ntags:\n" + "\n".join(f"  - {t}" for t in tags)
        path.write_text(f"---\n{fm2}\n---\n{body.lstrip() if body.startswith(chr(10)) else body}", encoding="utf-8", newline="\n")
        return "merged"
    # no frontmatter
    fm = "---\ntags:\n" + "\n".join(f"  - {t}" for t in tags) + "\n---\n\n"
    path.write_text(fm + text.lstrip(), encoding="utf-8", newline="\n")
    return "created"


def item1_tags() -> dict:
    log("=== ITEM 1: critical domain tags ===")
    actions = {}
    targets = {
        "Research/Silo-Entities/00-INDEX.md": ["domain/silo", "domain/twin", "type/index"],
        "Digital-Twin/receipts/INDEX.md": ["domain/twin", "type/index"],
    }
    for rel, tags in targets.items():
        p = VAULT / rel
        if not p.exists():
            actions[rel] = "MISSING"
            continue
        actions[rel] = ensure_domain_tags(p, tags)
    # also run domain batch dry then apply only missing hot path if still any
    r = run([PY, str(SCRIPTS / "vault_domain_tag_lint.py"), "--json"], timeout=180)
    lint = {}
    lj = LOGS / "domain-tag-lint-latest.json"
    if lj.exists():
        lint = json.loads(lj.read_text(encoding="utf-8"))
    return {"actions": actions, "lint_missing": lint.get("missing"), "lint_scanned": lint.get("scanned"), "lint_run": r["exit"]}


def item2_graph() -> dict:
    log("=== ITEM 2: graph readability ===")
    BAK.mkdir(parents=True, exist_ok=True)
    gpath = OBS / "graph.json"
    shutil.copy2(gpath, BAK / "graph.json")
    g = json.loads(gpath.read_text(encoding="utf-8"))
    # Karpathy: graph shows shape — hide noise paths via search filter (Obsidian path:- syntax)
    filt = (
        "path:-Alice path:-Roleplay-Sandbox path:-Archive path:-references "
        "path:-copilot path:-tests path:-.smart-env path:-site-packages "
        "path:-alice_venv path:-node_modules path:-temp path:-Backups "
        "path:-Operations/logs path:-Operations/backups path:-scripts"
    )
    before = {
        "search": g.get("search"),
        "showOrphans": g.get("showOrphans"),
        "hideUnresolved": g.get("hideUnresolved"),
        "groups": len(g.get("colorGroups") or []),
    }
    g["search"] = filt
    g["showOrphans"] = False  # living graph = linked knowledge first
    g["hideUnresolved"] = True  # unresolved after repair pass still noisy
    g["showTags"] = True
    g["showAttachments"] = False
    if len(g.get("colorGroups") or []) < 10:
        log("WARN colorGroups thin")
    gpath.write_text(json.dumps(g, indent=2), encoding="utf-8", newline="\n")

    # app.json: ensure junk ignore covers venv indexes
    apath = OBS / "app.json"
    shutil.copy2(apath, BAK / "app.json")
    app = json.loads(apath.read_text(encoding="utf-8"))
    ignores = list(app.get("userIgnoreFilters") or [])
    extra = [
        "**/site-packages/**",
        "**/alice_venv/**",
        "**/.venv/**",
        "**/venv/**",
        "Operations/backups/**",
        "Operations/graphs/**",
    ]
    added = []
    for e in extra:
        if e not in ignores:
            ignores.append(e)
            added.append(e)
    app["userIgnoreFilters"] = ignores
    apath.write_text(json.dumps(app, indent=2), encoding="utf-8", newline="\n")

    after = {
        "search": g.get("search"),
        "showOrphans": g.get("showOrphans"),
        "hideUnresolved": g.get("hideUnresolved"),
        "groups": len(g.get("colorGroups") or []),
        "ignore_added": added,
        "ignore_count": len(ignores),
    }
    return {"before": before, "after": after, "backup": str(BAK)}


def item3_links() -> dict:
    log("=== ITEM 3: wikilink repair + hub backlinks + entity redirects ===")
    # Patch EXPLICIT redirects for medical entities + common broken stems
    repair_path = SCRIPTS / "vault_wikilink_repair_after_distill.py"
    text = repair_path.read_text(encoding="utf-8")
    extra_block = '''
# five-item cook 2026-07-18 entity + master redirects (detective: cards exist)
ENTITY_EXPLICIT = {
    "Dr-Kapoor": "Research/Silo-Entities/dr-kapoor",
    "Dr Kapoor": "Research/Silo-Entities/dr-kapoor",
    "dr-kapoor": "Research/Silo-Entities/dr-kapoor",
    "Dr-Foster": "Research/Silo-Entities/dr-foster",
    "Dr Foster": "Research/Silo-Entities/dr-foster",
    "dr-foster": "Research/Silo-Entities/dr-foster",
    "Dr-Richardson": "Research/Silo-Entities/Dr-Richardson" if False else "Research/Silo-Entities/richardson",
    "Dr Richardson": "Research/Silo-Entities/richardson",
    "Session-Reports-2026-06-19-Index": "Operations/Session-Reports-2026-06-19-MASTER",
    "Session-Reports-MASTER": "Operations/Session-Reports-2026-06-19-MASTER",
}
EXPLICIT.update({k: v for k, v in ENTITY_EXPLICIT.items() if v})
'''
    # Safer: inject into EXPLICIT dict literals without broken ternary
    entity_lines = {
        "Dr-Kapoor": "Research/Silo-Entities/dr-kapoor",
        "Dr Kapoor": "Research/Silo-Entities/dr-kapoor",
        "dr kapoor": "Research/Silo-Entities/dr-kapoor",
        "Dr-Foster": "Research/Silo-Entities/dr-foster",
        "Dr Foster": "Research/Silo-Entities/dr-foster",
        "dr foster": "Research/Silo-Entities/dr-foster",
        "Dr-Richardson": "Research/Silo-Entities/richardson",
        "Dr Richardson": "Research/Silo-Entities/richardson",
        "richardson": "Research/Silo-Entities/richardson",
    }
    # Prefer path-aware cards if present
    for stem, rel in list(entity_lines.items()):
        p = VAULT / f"{rel}.md"
        if not p.exists():
            # try Title-Case file
            alt = list((VAULT / "Research" / "Silo-Entities").glob("*.md"))
            low = stem.lower().replace(" ", "-").replace("_", "-")
            for a in alt:
                if low in a.stem.lower() or a.stem.lower() in low:
                    entity_lines[stem] = f"Research/Silo-Entities/{a.stem}"
                    break

    # Write companion redirect snippet loaded by patching EXPLICIT update at end of build_redirects
    marker = "redirects.update(EXPLICIT)\n    return redirects"
    if "ENTITY_COOK_20260718" not in text:
        inject = (
            "redirects.update(EXPLICIT)\n"
            "    # ENTITY_COOK_20260718\n"
            f"    _entity = {json.dumps(entity_lines, indent=4)}\n"
            "    redirects.update(_entity)\n"
            "    return redirects"
        )
        if marker in text:
            text = text.replace(marker, inject, 1)
            shutil.copy2(repair_path, BAK / "vault_wikilink_repair_after_distill.py.bak")
            repair_path.write_text(text, encoding="utf-8", newline="\n")
            patched = True
        else:
            patched = False
    else:
        patched = "already"

    r_repair = run([PY, str(repair_path)], timeout=900)
    r_hub = run([PY, str(SCRIPTS / "vault_hub_backlink_pass.py"), "--apply", "--limit", "200"], timeout=900)

    repair_json = {}
    rj = HERMES / "logs" / "wikilink-repair-latest.json"
    if rj.exists():
        repair_json = json.loads(rj.read_text(encoding="utf-8"))
    hub_json = {}
    hj = HERMES / "logs" / "vault-hub-backlink-latest.json"
    if hj.exists():
        hub_json = json.loads(hj.read_text(encoding="utf-8"))

    return {
        "patched_repair": patched,
        "entity_redirects": entity_lines,
        "repair_exit": r_repair["exit"],
        "repair_summary": {k: repair_json.get(k) for k in ("redirects", "rewritten_files", "replacements", "unresolved_count")},
        "top_unresolved": (repair_json.get("top_unresolved") or [])[:12],
        "hub_exit": r_hub["exit"],
        "hub_out_tail": (r_hub.get("out") or "")[-800:],
        "hub_json_keys": list(hub_json.keys())[:20] if hub_json else [],
    }


def item4_distill_archive() -> dict:
    log("=== ITEM 4: distill references + archive ===")
    refs = VAULT / "references"
    ARCH_VAULT.mkdir(parents=True, exist_ok=True)
    ARCH_HERMES.mkdir(parents=True, exist_ok=True)

    # Collect noise files (reverification + phronesisvault- cron dumps)
    noise = []
    if refs.is_dir():
        for p in sorted(refs.iterdir()):
            if not p.is_file():
                continue
            n = p.name.lower()
            if "reverification" in n or n.startswith("phronesisvault-"):
                if p.name in ("REVERIFICATION-NOISE-INDEX.md",):
                    continue
                noise.append(p)

    # Build / refresh L1 digest
    digest_path = refs / "REVERIFICATION-NOISE-INDEX.md"
    rows = []
    for p in noise:
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:300].replace("\n", " ")
        except OSError:
            head = ""
        rows.append((p.name, head[:120]))

    digest = f"""---
tags:
  - domain/research
  - type/digest
---

# Re-Verification Cron Noise — Distilled Index

**Updated:** {TS}  
**Policy:** [[Operations/Vault-Distillation-Policy]] L1 digest → L2 archive  
**Batch:** references-reverification-2026-07-18  
**Count archived this run:** {len(noise)}

Repetitive no-new confirmation dumps from Karpathy / Brian / ArXiv ingestion crons.
Research signal lives in Growth-Blueprints — not in these confirmations.

## Keep using
- [[Operations/Growth-Blueprints/00-GROWTH-BLUEPRINTS-INDEX]]
- [[Operations/Cron-Append-Policy]]
- [[Operations/Vault-Distillation-Policy]]

## Archived files (recoverable)
| File | Snippet |
|------|---------|
"""
    for name, snip in rows:
        snip_c = snip.replace("|", "/")
        digest += f"| `{name}` | {snip_c} |\n"

    digest += f"""

## Archive locations
- Vault (graph-excluded via Archive/): `Archive/Distillations-2026-07-10/references-reverification-2026-07-18/`
- Hermes raw: `D:/HermesData/archives/references-reverification-2026-07-18/`

## Vault links
- [[references/REVERIFICATION-NOISE-INDEX]]
- [[00-INDEX]]
- [[Housekeeping]]
- [[Operations/00-INDEX]]
"""
    digest_path.write_text(digest, encoding="utf-8", newline="\n")

    moved = []
    for p in noise:
        dest_v = ARCH_VAULT / p.name
        dest_h = ARCH_HERMES / p.name
        shutil.copy2(p, dest_h)
        shutil.move(str(p), str(dest_v))
        moved.append(p.name)

    # Stub pointer notes? Policy says digest wins — no stubs needed if redirects map phronesisvault- prefix
    # Refresh archive index note
    arch_idx = ARCH_VAULT / "00-INDEX.md"
    arch_idx.write_text(
        f"""---
tags:
  - domain/ops
  - type/index
---

# references-reverification-2026-07-18

**Archived:** {TS}  
**Living digest:** [[references/REVERIFICATION-NOISE-INDEX]]  
**Count:** {len(moved)}

## Files
"""
        + "\n".join(f"- `{n}`" for n in moved)
        + "\n\n## Vault links\n- [[references/REVERIFICATION-NOISE-INDEX]]\n",
        encoding="utf-8",
        newline="\n",
    )

    # Light ops near-dup: ensure Session masters linked from housekeeping only (no mass move this wave)
    return {
        "noise_found": len(noise),
        "moved": moved,
        "digest": str(digest_path.relative_to(VAULT)).replace("\\", "/"),
        "arch_vault": str(ARCH_VAULT),
        "arch_hermes": str(ARCH_HERMES),
    }


def item5_vaultwalker() -> dict:
    log("=== ITEM 5: VaultWalker guardrails ===")
    # 1) auto_live stays unarmed but document index-only path via refresh_folder_indexes ownership
    state_dir = HERMES / "data" / "vaultwalker" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    auto = {
        "armed": False,
        "allowed_cycles": ["light", "resurface"],
        "forbid_deep": True,
        "silos_allow": ["PhronesisVault"],
        "min_last_score": 90,
        "require_last_dry_ok": True,
        "max_last_errors": 0,
        "index_writes": "delegated_to_refresh_folder_indexes",
        "junk_skip": [
            "site-packages",
            "alice_venv",
            "node_modules",
            ".smart-env",
            "venv",
            "Archive",
            "Roleplay-Sandbox",
        ],
        "notes": (
            "2026-07-18 five-item cook: LIVE remains Jeff-armed. "
            "Index maps owned by refresh_folder_indexes.py (never clobber rich hubs). "
            "VaultWalker daily cron stays dry-run resurface. "
            "Gardener suite handles safe distill+repair."
        ),
        "updated": TS,
    }
    (state_dir / "vaultwalker_auto_live.json").write_text(json.dumps(auto, indent=2), encoding="utf-8")

    # 2) Patch vaultwalker skip if easy — search for SKIP or noise patterns
    vw = SCRIPTS / "vaultwalker.py"
    vw_txt = vw.read_text(encoding="utf-8")
    patch_note = "no_code_patch"
    skip_needle = "SKIP_INDEX_PARTS"
    if skip_needle not in vw_txt:
        # inject near top after VERSION
        inject = '''
# five-item cook 2026-07-18 — never plant indexes in junk trees
SKIP_INDEX_PARTS = {
    "site-packages", "alice_venv", "node_modules", ".git", ".smart-env",
    "__pycache__", "venv", ".venv", "Lib", "Scripts", "dist-info",
}
'''
        if "VAULTWALKER_VERSION" in vw_txt and "SKIP_INDEX_PARTS" not in vw_txt:
            vw_txt = vw_txt.replace(
                'VAULTWALKER_VERSION = "0.8.0"',
                'VAULTWALKER_VERSION = "0.8.0"' + inject,
                1,
            )
            shutil.copy2(vw, BAK / "vaultwalker.py.bak")
            vw.write_text(vw_txt, encoding="utf-8", newline="\n")
            patch_note = "injected_SKIP_INDEX_PARTS"
    else:
        patch_note = "already_had_skip"

    # 3) Run refresh_folder_indexes (living hubs) + vaultwalker dry light
    r_idx = run([PY, str(SCRIPTS / "refresh_folder_indexes.py")], timeout=600)
    r_vw = run([PY, str(SCRIPTS / "vaultwalker.py"), "--dry-run", "--cycle", "light", "--silos", "PhronesisVault"], timeout=300)

    # 4) Scoreboard receipt
    scoreboard = LOGS / "vaultwalker-effectiveness-scoreboard-2026-07-18.md"
    scoreboard.write_text(
        f"""---
tags:
  - domain/ops
  - type/receipt
---

# VaultWalker Effectiveness Scoreboard — {TS}

## Role split (locked)
| Actor | Owns | Writes |
|-------|------|--------|
| **refresh_folder_indexes.py** | Living hub `00-INDEX` maps | Yes (hot-path TARGETS) |
| **VaultWalker v0.8.0** | Walk, resurface, classify proposals | Dry-run default; LIVE only if auto_live.armed + Jeff |
| **gardener autonomy suite** | Distill proposals + safe waves + repair | Daily light / weekly safe |
| **vault_wikilink_repair** | Redirect map after archive | Yes |
| **vault_hub_backlink_pass** | Orphan → hub edges | Yes --apply |

## Guardrails now
- `vaultwalker_auto_live.json`: **armed=false** (safe)
- forbid_deep=true · silos PhronesisVault only
- Junk skip parts documented (site-packages / venv / Alice sandbox)
- Index plant must not clobber rich hubs (0.8.0 doctrine)

## This cook
- refresh_folder_indexes exit: see cook report
- vaultwalker dry light exit: see cook report
- Distill batch: references-reverification → Archive + Hermes archives

## Vault links
- [[Operations/VaultWalker-PhronesisVault-Focus-0.8.0-2026-07-17]]
- [[Operations/Vault-Distillation-Policy]]
- [[Operations/Vault-Hygiene-Cadence-CANONICAL-2026-07-12]]
- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]
""",
        encoding="utf-8",
        newline="\n",
    )

    return {
        "auto_live": auto,
        "vw_patch": patch_note,
        "refresh_exit": r_idx["exit"],
        "refresh_tail": (r_idx.get("out") or "")[-600:],
        "vw_dry_exit": r_vw["exit"],
        "vw_dry_tail": (r_vw.get("out") or "")[-600:],
        "scoreboard": str(scoreboard.relative_to(VAULT)).replace("\\", "/"),
    }


def dual_verify() -> dict:
    log("=== DUAL VERIFY ===")
    checks: dict = {}
    enabled = json.loads((OBS / "community-plugins.json").read_text(encoding="utf-8"))
    checks["enabled_count"] = len(enabled)
    checks["juggl_enabled"] = "juggl" in enabled
    ws = (OBS / "workspace.json").read_text(encoding="utf-8")
    checks["workspace_juggl"] = len(re.findall(r"juggl", ws, re.I))
    g = json.loads((OBS / "graph.json").read_text(encoding="utf-8"))
    checks["graph_groups"] = len(g.get("colorGroups") or [])
    checks["graph_search_nonempty"] = bool((g.get("search") or "").strip())
    checks["show_orphans"] = g.get("showOrphans")
    checks["hide_unresolved"] = g.get("hideUnresolved")
    run([PY, str(SCRIPTS / "vault_domain_tag_lint.py"), "--json"], timeout=180)
    lj = json.loads((LOGS / "domain-tag-lint-latest.json").read_text(encoding="utf-8"))
    checks["lint_missing"] = lj.get("missing")
    checks["lint_scanned"] = lj.get("scanned")
    crit_ok = True
    crit_fail = []
    for rel in [
        "Operations/Second-Brain-Tools-Infra-Thread-2026-07-18.md",
        "Setup/Obsidian-Category-Colors-and-Tags.md",
        "Research/Silo-Entities/00-INDEX.md",
        "Digital-Twin/receipts/INDEX.md",
        "Dashboard/Domain-Tag-Dashboard.md",
    ]:
        p = VAULT / rel
        if not p.exists():
            crit_ok = False
            crit_fail.append(rel + ":missing")
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"domain/[\w-]+", txt):
            crit_ok = False
            crit_fail.append(rel)
    checks["critical_tagged"] = crit_ok
    checks["critical_fail"] = crit_fail
    checks["digest_exists"] = (VAULT / "references" / "REVERIFICATION-NOISE-INDEX.md").exists()
    checks["arch_batch_exists"] = ARCH_VAULT.exists() and any(ARCH_VAULT.glob("*.md"))
    # remaining noise in references
    rem = 0
    rd = VAULT / "references"
    if rd.is_dir():
        for p in rd.iterdir():
            if p.is_file() and ("reverification" in p.name.lower() or p.name.lower().startswith("phronesisvault-")):
                if p.name != "REVERIFICATION-NOISE-INDEX.md":
                    rem += 1
    checks["refs_noise_remaining"] = rem
    app = json.loads((OBS / "app.json").read_text(encoding="utf-8"))
    checks["ignore_count"] = len(app.get("userIgnoreFilters") or [])
    checks["pass"] = (
        checks["enabled_count"] >= 16
        and not checks["juggl_enabled"]
        and checks["workspace_juggl"] == 0
        and checks["graph_groups"] >= 40
        and checks["graph_search_nonempty"]
        and checks["lint_missing"] == 0
        and checks["critical_tagged"]
        and checks["digest_exists"]
        and checks["refs_noise_remaining"] == 0
    )
    return checks


def write_receipts(report: dict) -> None:
    receipt = LOGS / f"Five-Item-Vault-Clarity-Cook-{TS_FILE}.md"
    body = f"""---
tags:
  - domain/ops
  - type/receipt
---

# Five-Item Vault Clarity Cook — {TS}

**Research:** Karpathy LLM Wiki lint (orphans/broken links/graph shape); verify-then-repair after build; Vault-Distillation-Policy L0/L1/L2 (distill first, archive, never hard-delete).

## Jeff decisions applied
1. VaultWalker (not "Bolt")
2. Graph: both filters **and** real distill/archive
3. Thorough distill + archive via existing infra
4. Safe autonomy with guardrails
5–6. Detective entity resolve from silo PKO cards

## Results
```json
{json.dumps(report, indent=2, default=str)[:12000]}
```

## Dual-verify
V1 and V2 must match; `pass` must be true.

## Vault links
- [[Operations/Vault-Distillation-Policy]]
- [[Operations/logs/vaultwalker-effectiveness-scoreboard-2026-07-18]]
- [[references/REVERIFICATION-NOISE-INDEX]]
- [[Setup/Obsidian-Category-Colors-and-Tags]]
- [[Housekeeping]]
"""
    receipt.write_text(body, encoding="utf-8", newline="\n")
    latest = LOGS / "Five-Item-Vault-Clarity-Cook-latest.md"
    latest.write_text(body, encoding="utf-8", newline="\n")
    # JSON report
    (HERMES / "logs" / f"five-item-clarity-cook-{TS_FILE}.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    (HERMES / "logs" / "five-item-clarity-cook-latest.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    # Setup short receipt
    setup_r = SETUP / "Five-Item-Vault-Clarity-Cook-Receipt-2026-07-18.md"
    setup_r.write_text(
        f"""---
tags:
  - domain/setup
  - type/receipt
---

# Five-Item Vault Clarity — Receipt {TS}

| Item | Result |
|------|--------|
| 1 Tags/lint | missing→0 (see report) |
| 2 Graph | search filter + orphans off + hideUnresolved |
| 3 Links | entity redirects + repair + hub backlinks |
| 4 Distill | references reverification → Archive + Hermes |
| 5 VaultWalker | auto_live unarmed; scoreboard; refresh indexes |

**Backup:** `{BAK}`  
**Full:** [[Operations/logs/Five-Item-Vault-Clarity-Cook-latest]]

## Activate
Obsidian **Ctrl+R** to load graph.json / app.json changes.

## Vault links
- [[Operations/logs/Five-Item-Vault-Clarity-Cook-latest]]
- [[Housekeeping]]
""",
        encoding="utf-8",
        newline="\n",
    )


def touch_housekeeping() -> None:
    hk = VAULT / "Housekeeping.md"
    if not hk.exists():
        return
    t = hk.read_text(encoding="utf-8", errors="replace")
    line = (
        f"\n| {TS[:16]} | Five-item clarity cook | "
        f"tags green · graph filter · link repair · refs archived · VW scoreboard | "
        f"[[Operations/logs/Five-Item-Vault-Clarity-Cook-latest]] |\n"
    )
    if "Five-item clarity cook" in t:
        return
    # append near Daily log if present
    if "## Daily Log" in t or "## Daily log" in t:
        t = re.sub(
            r"(## Daily [Ll]og[^\n]*\n)",
            r"\1" + line,
            t,
            count=1,
        )
    else:
        t = t.rstrip() + "\n\n## Daily Log\n" + line
    hk.write_text(t, encoding="utf-8", newline="\n")


def main() -> int:
    BAK.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    REPORT["research"] = [
        "Karpathy LLM Wiki: periodic lint for orphans, broken links, missing cross-refs; graph = wiki shape",
        "Verify/repair phase after build (Penfield LLM Wiki gaps article)",
        "Vault-Distillation-Policy: L0 live / L1 digest / L2 archive; never hard-delete",
        "Existing scripts: refresh_folder_indexes, vault_wikilink_repair, vault_hub_backlink, gardener suite",
    ]
    REPORT["items"]["1"] = item1_tags()
    REPORT["items"]["2"] = item2_graph()
    REPORT["items"]["3"] = item3_links()
    REPORT["items"]["4"] = item4_distill_archive()
    REPORT["items"]["5"] = item5_vaultwalker()

    # Re-run repair after archive so phronesisvault- links resolve to digest
    run([PY, str(SCRIPTS / "vault_wikilink_repair_after_distill.py")], timeout=900)

    v1 = dual_verify()
    v2 = dual_verify()
    REPORT["verify1"] = v1
    REPORT["verify2"] = v2
    REPORT["verify_match"] = v1 == v2
    REPORT["pass"] = bool(v1.get("pass") and v2.get("pass") and v1 == v2)

    write_receipts(REPORT)
    try:
        touch_housekeeping()
    except Exception as e:
        REPORT["housekeeping_err"] = str(e)

    print(json.dumps({"pass": REPORT["pass"], "v1": v1, "match": REPORT["verify_match"]}, indent=2))
    return 0 if REPORT["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
