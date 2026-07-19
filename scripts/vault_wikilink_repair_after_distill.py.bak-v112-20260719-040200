#!/usr/bin/env python3
"""Repair Obsidian wikilinks after Phase B distill/archive waves.

1) Build redirect map: archived basename -> living digest/master
2) Scan living vault md (skip Archive deep bulk optional)
3) Rewrite [[Old-Name]] -> [[New-Digest]] where mapped
4) Report remaining unresolved (sample)
5) Optionally append L4 hub links on digests missing them
"""
from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict

VAULT = Path(r"D:\PhronesisVault")
ARCH = VAULT / "Archive" / "Distillations-2026-07-10"
OUT_JSON = Path(r"D:\HermesData\logs\wikilink-repair-latest.json")
OUT_MD = VAULT / "Operations" / "logs" / "wikilink-repair-latest.md"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d")

LINK_RE = re.compile(r"\[\[([^\]|#]+)(\|[^\]]+)?\]\]")

# Explicit redirects from wave digests
EXPLICIT = {
    "Memory-Delta-Sessions-ROLLUP-2026-06-18": "Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18",
    "Automated-Routing-Batches-DIGEST": "Operations/Automated-Routing-Batches-DIGEST",
    "Secrets-Proposals-Batches-DIGEST": "Operations/Secrets-Proposals-Batches-DIGEST",
    "Session-Handoffs-DIGEST": "Operations/Session-Handoffs-DIGEST",
    "Session-Reports-2026-06-19-MASTER": "Operations/Session-Reports-2026-06-19-MASTER",
    "Operations/Session-Reports-2026-06-19-MASTER": "Operations/Session-Reports-2026-06-19-MASTER",
    "Session-Reports-2026-06-19-Index": "Operations/Session-Reports-2026-06-19-Index",
    "Operations/Session-Reports-2026-06-19-Index": "Operations/Session-Reports-2026-06-19-Index",
    "daily-distillation-INDEX": "Operations/logs/daily-distillation-INDEX",
    "VaultWalker-Safe-Gardener-2026-07-10": "Operations/VaultWalker-Safe-Gardener-2026-07-10",
    "VaultWalker-Snapshots-INDEX": "Operations/VaultWalker-Snapshots-INDEX",
    "Operations/VaultWalker-Snapshots-INDEX": "Operations/VaultWalker-Snapshots-INDEX",
    "HERMES-CONFIG-MAP": "Discord/configs/HERMES-CONFIG-MAP",
    "Resurfaced-Ideas-CORE": "Research/Resurfaced-Ideas-CORE",
    "REVERIFICATION-NOISE-INDEX": "references/REVERIFICATION-NOISE-INDEX",
    "references/REVERIFICATION-NOISE-INDEX": "references/REVERIFICATION-NOISE-INDEX",
    "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10": "Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10",
    "Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10": "Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10",
    "Cron-Append-Policy": "Operations/Cron-Append-Policy",
    # Wave-2 2026-07-18 clarity cook
    "Vault-Link-Lint-latest": "Operations/Vault-Link-Lint-latest",
    "Operations/Vault-Link-Lint-latest": "Operations/Vault-Link-Lint-latest",
    "Bases/Domain-Tag-Index": "Bases/Domain-Tag-Index",
    "Domain-Tag-Index": "Bases/Domain-Tag-Index",
    "Bases/Setup-Playbooks": "Bases/Setup-Playbooks",
    "Setup-Playbooks": "Bases/Setup-Playbooks",
    "Hermes-Factual-vs-RP-Sanity-Walkthrough": "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    "Operations/Phronesis-Curator-Librarian": "Operations/STATUS",
    "Phronesis-Curator-Librarian": "Operations/STATUS",
    # Wave-3 2026-07-18 residual clearance
    "REVERIFICATION-NOISE-INDEX": "references/REVERIFICATION-NOISE-INDEX",
    "references/REVERIFICATION-NOISE-INDEX": "references/REVERIFICATION-NOISE-INDEX",
    "00-MASTER-K-SOVEREIGN-INDEX": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "00-MASTER-K-SOVEREIGN-INDEX.md": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "K:/Phronesis-Sovereign/00-MASTER-K-SOVEREIGN-INDEX": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "K:/Phronesis-Sovereign/00-MASTER-K-SOVEREIGN-INDEX.md": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "K:\\Phronesis-Sovereign\\00-MASTER-K-SOVEREIGN-INDEX": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "K:\\Phronesis-Sovereign\\00-MASTER-K-SOVEREIGN-INDEX.md": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "scripts/classify_ingest.py": "Digital-Twin/Ingestion-Pipeline-Checklist",
    "scripts/sovereign_router": "Operations/Sovereign-FIFO-DIGEST",
    "scripts/model_inventory.py": "Operations/STATUS",
    "Operations/logs/log-intelligence/Log-Intelligence-Digest": "Operations/logs/daily-distillation-INDEX",
    "Log-Intelligence-Digest": "Operations/logs/daily-distillation-INDEX",
    "Roleplay-Sandbox/runtime/IMAGE-PIPELINE": "Operations/STATUS",
    "Roleplay-Sandbox/runtime/triplet-prompt-variations": "Operations/STATUS",
    "Archive/Graphiti-FalkorDB-Legacy-Distillation": "Archive-Index",
    "wikilinks": "Operations/Vault-Link-Lint-latest",
    # Wave-3 residual round 2
    "Skills Registry": "Operations/Skills-Safe-Incorporate-Silo-CANONICAL-2026-07-12",
    "Digital-Twin/Audit-Dashboard.md": "Digital-Twin/Audit-Dashboard-Prototype",
    "Digital-Twin/Audit-Dashboard": "Digital-Twin/Audit-Dashboard-Prototype",
    "Audit-Dashboard": "Digital-Twin/Audit-Dashboard-Prototype",
    "ComfyUI Architecture": "Operations/ComfyUI-Batch-Research-Refs-2026-07-04",
    "ComfyUI Pony Setup": "Operations/ComfyUI-Batch-Research-Refs-2026-07-04",
    "docs/agent-coordination/Thread-Update-Receipt-2026-06-27-Autonomous-Run.md": "docs/agent-coordination/Thread-Update-Receipts-DIGEST",
    "docs/agent-coordination/Thread-Update-Receipt-2026-06-27-Autonomous-Run": "docs/agent-coordination/Thread-Update-Receipts-DIGEST",
    "skills/autonomy/harness-evolution/SKILL.md": "Research/Harness-Evolution",
    "harness-evolution": "Research/Harness-Evolution",
    "Person": "Research/Silo-Entities/00-LIFE-GRAPH",
    "Note": "00-INDEX",
    "MyBase.base": "Bases/Setup-Playbooks",
    "MyBase": "Bases/Setup-Playbooks",
    "_INDEX.md": "00-INDEX",
    "_INDEX": "00-INDEX",
    "Operations/Sovereign-Stack-Health-Check related": "Operations/STATUS",
    "Evo-Loop-Sandbox-2026-07-01": "Operations/STATUS",
    "../manifests/k-manifest-data-model.md": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "../Operations/Data-Silo-Pipeline-Progress.md": "Digital-Twin/Ingestion-Pipeline-Checklist",
    # Wave-3 residual round 3 (long-tail titles)
    "Hermes Bible Learn": "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    "Skill Self-Evolution": "Research/Harness-Evolution",
    "Multi-Agent Architecture": "Operations/STATUS",
    "K: Silo Design": "Digital-Twin/K-Sovereign-Master-Index-Pointer",
    "Hermes-RP-Sandbox-Boundary": "Operations/Hermes-Factual-vs-RP-Sanity-Walkthrough-2026-07-17",
    "Research/Fieldy-Insights": "Research/00-INDEX",
    "MOCs/Alice-MOC": "Operations/STATUS",
    "Operations/Pause-Point-2026-06-19-Local-First-Pivot.md": "Operations/STATUS",
    "Operations/Pause-Point-2026-06-19-Local-First-Pivot": "Operations/STATUS",
    "Operations/SCRIPTS-MANIFEST": "Operations/STATUS",
    "Operations/future_projects_parking": "Operations/STATUS",
    "links": "Operations/Vault-Link-Lint-latest",
    "image.png": "Operations/STATUS",
}


def stem(path: Path) -> str:
    return path.stem


def build_redirects() -> dict[str, str]:
    """Map archived file stems -> best living target path without .md."""
    redirects: dict[str, str] = {}
    # from archive files to nearest digest by folder
    folder_default = {
        "Memory-Deltas": "Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18",
        "Daily-Distillation": "Operations/logs/daily-distillation-INDEX",
        "Routing-Batches": "Operations/Automated-Routing-Batches-DIGEST",
        "Secrets-Batches": "Operations/Secrets-Proposals-Batches-DIGEST",
        "Session-Handoffs": "Operations/Session-Handoffs-DIGEST",
        "Thread-Receipts": "docs/agent-coordination/Thread-Update-Receipts-DIGEST",
        "june19-reports": "Operations/Session-Reports-2026-06-19-MASTER",
        "vaultwalker-snapshots": "Operations/VaultWalker-Snapshots-INDEX",
        "near-dup-pairs": "Operations/Session-Reports-2026-06-19-MASTER",
        "reverification-noise": "references/REVERIFICATION-NOISE-INDEX",
        "test-logs": "tests/logs/TEST-LOGS-INDEX",
        "es_ingest": "AI-Zone/ingested/es_ingest_INDEX",
        "review-moc": "AI-Zone/review-moc/review-moc-pilots-DIGEST",
        "review-moc-batch-es": "AI-Zone/review-moc/review-moc-batch-es-ingest-INDEX",
        "discord-hermes-config-archives": "Discord/configs/HERMES-CONFIG-MAP",
        "cluster-ollama": "Operations/Session-Reports-2026-06-19-MASTER",
        "cluster-microstep2": "Operations/Session-Reports-2026-06-19-MASTER",
        "cluster-tiny-classifier": "Operations/Session-Reports-2026-06-19-MASTER",
    }
    if ARCH.exists():
        for p in ARCH.rglob("*.md"):
            if p.name.lower() in ("readme.md", "00-index.md", "index.md"):
                continue
            # parent folder name as key
            for part in p.parts:
                if part in folder_default:
                    redirects[p.stem] = folder_default[part]
                    break
            # also map without date noise
    # prefix rules
    prefix_map = [
        ("Memory-Delta-", "Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18"),
        ("Automated-Routing-Batch-", "Operations/Automated-Routing-Batches-DIGEST"),
        ("Secrets-Proposals-Batch-", "Operations/Secrets-Proposals-Batches-DIGEST"),
        ("Session-Handoff-", "Operations/Session-Handoffs-DIGEST"),
        ("daily-distillation-", "Operations/logs/daily-distillation-INDEX"),
        ("Thread-Update-Receipt-", "docs/agent-coordination/Thread-Update-Receipts-DIGEST"),
        ("es_ingest_", "AI-Zone/ingested/es_ingest_INDEX"),
        ("review-moc-pilot", "AI-Zone/review-moc/review-moc-pilots-DIGEST"),
        ("review-moc-batch_es_ingest", "AI-Zone/review-moc/review-moc-batch-es-ingest-INDEX"),
        ("phronesisvault-arxiv-", "references/REVERIFICATION-NOISE-INDEX"),
        ("phronesisvault-brian-", "references/REVERIFICATION-NOISE-INDEX"),
        ("phronesisvault-karpathy-", "references/REVERIFICATION-NOISE-INDEX"),
        ("VaultWalker-Observations", "Operations/VaultWalker-Snapshots-INDEX"),
        ("VaultWalker-Post-Conformity", "Operations/VaultWalker-Snapshots-INDEX"),
        ("VaultWalker-Status-", "Operations/VaultWalker-Snapshots-INDEX"),
        ("MicroStep2-", "Operations/Session-Reports-2026-06-19-MASTER"),
        ("Ollama-", "Operations/Session-Reports-2026-06-19-MASTER"),
        ("Tiny-Classifier-", "Operations/Session-Reports-2026-06-19-MASTER"),
        ("Llama-Server-Launch", "Operations/Llama-Server-Launch-DIGEST"),
        ("LlamaServer-Launch", "Operations/Llama-Server-Launch-DIGEST"),
        ("Sovereign-FIFO-Queue", "Operations/Sovereign-FIFO-DIGEST"),
        ("Sovereign-Router-FIFO", "Operations/Sovereign-FIFO-DIGEST"),
        ("phronesisvault-", "references/REVERIFICATION-NOISE-INDEX"),
        ("Sovereign-Stack-Health-Check-2026-06-24-round", "docs/agent-coordination/STATUS"),
    ]
    # apply prefix for any stem we know from archive listing
    if ARCH.exists():
        for p in ARCH.rglob("*.md"):
            s = p.stem
            for pref, dest in prefix_map:
                if s.startswith(pref) or pref in s:
                    redirects[s] = dest
    redirects.update(EXPLICIT)
    # ENTITY_COOK_20260718
    _entity = {
    "Dr-Kapoor": "Research/Silo-Entities/dr-kapoor",
    "Dr Kapoor": "Research/Silo-Entities/dr-kapoor",
    "dr kapoor": "Research/Silo-Entities/dr-kapoor",
    "Dr-Foster": "Research/Silo-Entities/dr-foster",
    "Dr Foster": "Research/Silo-Entities/dr-foster",
    "dr foster": "Research/Silo-Entities/dr-foster",
    "Dr-Richardson": "Research/Silo-Entities/richardson",
    "Dr Richardson": "Research/Silo-Entities/richardson",
    "richardson": "Research/Silo-Entities/richardson"
}
    redirects.update(_entity)
    return redirects


def resolve_exists(target: str) -> bool:
    """Conservative direct check; prefer file_exists_fast with indexes."""
    t = target.strip().replace("\\", "/")
    if t.endswith(".md"):
        t = t[:-3]
    ts = t.rstrip("/")
    candidates = [
        VAULT / f"{ts}.md",
        VAULT / f"{ts}.base",
        VAULT / f"{ts}.canvas",
        VAULT / f"{ts}.json",
        VAULT / ts,
        VAULT / "Operations" / f"{Path(ts).name}.md",
        VAULT / "docs" / "agent-coordination" / f"{Path(ts).name}.md",
        VAULT / "Bases" / f"{Path(ts).name}.md",
        VAULT / "Bases" / f"{Path(ts).name}.base",
    ]
    return any(c.exists() for c in candidates)


def file_exists_fast(target: str, living_stems: set[str], living_paths: set[str]) -> bool:
    t = target.strip().replace("\\", "/")
    if t.startswith("http"):
        return True
    # Absolute external paths are not vault notes
    if re.match(r"^[A-Za-z]:[/\\]", t) or t.startswith("//"):
        return False
    if t.endswith(".md"):
        t = t[:-3]
    ts = t.rstrip("/")
    if t in living_paths or t.lower() in living_paths:
        return True
    if ts in living_paths or ts.lower() in living_paths:
        return True
    # Bare-stem only for path-free names (avoid SKILL.md collisions)
    if "/" not in ts and "\\" not in ts:
        name = Path(ts).name
        stem = name
        for ext in (".base", ".canvas", ".json"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
        if stem in living_stems or stem.lower() in living_stems:
            return True
        if name in living_stems or name.lower() in living_stems:
            return True
    name = Path(ts).name
    for p in (
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
    ):
        if p.exists():
            return True
    return False


# Living-CNS skip set (aligned with vault_living_unresolved_scan + graph taste C)
LIVING_SKIP_PARTS = {
    ".obsidian",
    "site-packages",
    "node_modules",
    ".git",
    "alice_venv",
    "__pycache__",
    "backups",
}
LIVING_SKIP_PREFIXES = (
    "Archive/",
    "Alice/",
    "Roleplay-Sandbox/",
    "Operations/backups/",
    "Backups/",
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


def _rel(p: Path) -> str:
    return str(p.relative_to(VAULT)).replace("\\", "/")


def is_living_path(p: Path) -> bool:
    r = _rel(p)
    if any(x in p.parts for x in LIVING_SKIP_PARTS):
        return False
    if any(r.startswith(pref) for pref in LIVING_SKIP_PREFIXES):
        return False
    return True


def build_living_indexes() -> tuple[set[str], set[str]]:
    """Index living md + base + canvas (+ json) for rewrite decisions.

    Physical resolve still uses file_exists_fast which also checks disk.
    """
    stems: set[str] = set()
    paths: set[str] = set()
    # Full vault stems for resolve (except junk/backups) so targets under
    # references/Archive still resolve when files exist.
    junk = {".obsidian", "site-packages", "node_modules", ".git", "alice_venv", "backups"}
    for pat in ("*.md", "*.base", "*.canvas", "*.json"):
        for p in VAULT.rglob(pat):
            if any(x in p.parts for x in junk):
                continue
            # Exclude Phase B distill bulk so redirects to digests apply
            if "Distillations-2026-07-10" in p.parts:
                continue
            rel = _rel(p)
            rel0 = rel.rsplit(".", 1)[0]
            paths.add(rel0)
            paths.add(rel0.lower())
            paths.add(rel)
            stems.add(p.stem)
            stems.add(p.stem.lower())
    return stems, paths


def main() -> int:
    redirects = build_redirects()
    living_stems, living_paths = build_living_indexes()

    rewritten_files = 0
    replacements = 0
    unresolved: list[tuple[str, str]] = []
    replaced_examples: list[str] = []

    skip_parts = {".obsidian", "site-packages", "node_modules", ".git", "alice_venv", "backups"}
    # Never rewrite inside noise/backup trees (prevents backup pollution)
    no_write_prefixes = (
        "Operations/backups/",
        "Backups/",
        "Alice/",
        "Roleplay-Sandbox/",
        "Archive/Distillations-2026-07-10/",
    )

    for p in VAULT.rglob("*.md"):
        if any(x in p.parts for x in skip_parts):
            continue
        rel = _rel(p)
        if any(rel.startswith(pref) for pref in no_write_prefixes):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def repl(m: re.Match) -> str:
            nonlocal replacements
            raw = m.group(1).strip()
            alias = m.group(2) or ""
            key = raw.replace("\\", "/")
            base = Path(key).name
            dest = None
            if base in redirects:
                dest = redirects[base]
            elif key in redirects:
                dest = redirects[key]
            else:
                for pref, d in [
                    ("Memory-Delta-", "Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18"),
                    ("Automated-Routing-Batch-", "Operations/Automated-Routing-Batches-DIGEST"),
                    ("daily-distillation-20", "Operations/logs/daily-distillation-INDEX"),
                    ("phronesisvault-", "references/REVERIFICATION-NOISE-INDEX"),
                ]:
                    if base.startswith(pref) or key.startswith(pref):
                        dest = d
                        break
            if dest and dest.replace("\\", "/") != key:
                if not file_exists_fast(key, living_stems, living_paths):
                    replacements += 1
                    if len(replaced_examples) < 40:
                        replaced_examples.append(f"{raw} -> {dest}")
                    return f"[[{dest}{alias}]]"
            return m.group(0)

        new = LINK_RE.sub(repl, text)
        if new != text:
            p.write_text(new, encoding="utf-8", newline="\n")
            rewritten_files += 1

    # second pass: unresolved ONLY from living-CNS notes (truth surface)
    for p in VAULT.rglob("*.md"):
        if not is_living_path(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in LINK_RE.finditer(text):
            raw = m.group(1).strip().replace("\\", "/")
            if raw.startswith("http"):
                continue
            if not file_exists_fast(raw, living_stems, living_paths):
                unresolved.append((_rel(p), raw))

    top = Counter(t for _, t in unresolved).most_common(30)

    # ensure key digests have hub footers
    hubs = [
        VAULT / "Operations" / "Session-Reports-2026-06-19-MASTER.md",
        VAULT / "Operations" / "Memory-Delta-Sessions-ROLLUP-2026-06-18.md",
        VAULT / "Operations" / "Automated-Routing-Batches-DIGEST.md",
        VAULT / "Operations" / "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10.md",
    ]
    footer = """

## Vault links
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]
- [[00-INDEX]]
"""
    for h in hubs:
        if not h.exists():
            continue
        t = h.read_text(encoding="utf-8", errors="ignore")
        if "## Vault links" not in t:
            h.write_text(t.rstrip() + footer, encoding="utf-8")
            rewritten_files += 1

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "redirects": len(redirects),
        "rewritten_files": rewritten_files,
        "replacements": replacements,
        "unresolved_count": len(unresolved),
        "top_unresolved": top[:30],
        "examples": replaced_examples[:30],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Wikilink Repair — {TS}",
        "",
        f"- Redirects known: **{len(redirects)}**",
        f"- Files rewritten: **{rewritten_files}**",
        f"- Link replacements: **{replacements}**",
        f"- Still unresolved (living vault): **{len(unresolved)}**",
        "",
        "## Example redirects applied",
    ]
    for e in replaced_examples[:20]:
        lines.append(f"- `{e}`")
    lines += ["", "## Top unresolved targets"]
    for t, n in top[:20]:
        lines.append(f"- ({n}) `{t}`")
    lines += [
        "",
        "## Vault links",
        "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("redirects", "rewritten_files", "replacements", "unresolved_count")}, indent=2))
    print("top_unresolved", top[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
