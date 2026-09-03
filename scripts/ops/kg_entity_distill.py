#!/usr/bin/env python3
"""Pre-bake <600 token Markdown dossiers from kg.jsonl. Local, no LLM required.

Banned silos skipped. Family names never invented — sourced triples only.

  python D:\\HermesData\\scripts\\ops\\kg_entity_distill.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

KG = Path(r"D:\HermesData\state\life_rag\kg.jsonl")
OUT = Path(r"D:\PhronesisVault\Entities")
INDEX = OUT / "00-INDEX.md"
BAN = (
    "patient-bloom",
    "medical-records",
    "navy-service",
    "roleplay-sandbox",
    "nutaku",
    "secrets-quarantine",
    "dicom",
    "volbrain",
)

# Named cores (dossier even if sparse).
FAMILY = [
    ("Gary", ("gary",)),
    ("Sara", ("sara",)),
    ("Jan", ("jan l", "jan bloom", "jan l. bloom")),
    ("Jodi", ("jodi",)),
    ("Jenni", ("jenni", "bloom-harris")),
    ("Anthony", ("anthony",)),
    ("Spencer", ("spencer",)),
    ("Blaizen", ("blaizen",)),
]
DOMAINS = [
    ("Booksbloom", ("booksbloom", "books bloom")),
    ("FLL-SPIKE-Prime", ("fll", "spike prime", "first lego")),
    ("Albion-Online", ("albion",)),
    ("OptiPlex-Sovereign-AI", ("optiplex", "qwythos", "rtx 3060", "7090")),
    ("ODU", ("odu", "old dominion")),
    ("Millbrook", ("millbrook",)),
]


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _banned(blob: str) -> bool:
    low = blob.lower()
    return any(b in low for b in BAN)


def load_triples(limit: int = 0) -> list[dict]:
    rows = []
    if not KG.is_file():
        return rows
    with KG.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            if limit and i > limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            blob = " ".join(str(rec.get(k) or "") for k in ("s", "r", "o", "src", "path"))
            if _banned(blob):
                continue
            rows.append(rec)
    return rows


def _hay(rec: dict) -> str:
    return " ".join(str(rec.get(k) or "") for k in ("s", "r", "o")).lower()


def match_needles(rec: dict, needles: tuple[str, ...]) -> bool:
    h = _hay(rec)
    return any(n in h for n in needles)


def cluster_hits(rows: list[dict], needles: tuple[str, ...], cap: int = 40) -> list[dict]:
    hits = [r for r in rows if match_needles(r, needles)]
    return hits[:cap]


def top_hubs(rows: list[dict], n: int = 12) -> list[str]:
    deg: Counter[str] = Counter()
    for r in rows:
        for k in ("s", "o"):
            v = str(r.get(k) or "").strip()
            if len(v) < 3 or v.lower() in {"self", "unknown", "00-family"}:
                continue
            if _banned(v):
                continue
            deg[v] += 1
    # Skip mega-hubs that are the operator identity
    skip = (
        "jeffrey",
        "jeff bloom",
        "mr.jeffrey",
        "facebook",
        "linkedin",
        "twitter",
        "phone",
        "live_sweep",
        "vector_sync",
        "voice:",
        "gmail",
        "unknown",
        "contacts_audit",
    )
    out = []
    for name, _c in deg.most_common(120):
        low = name.lower()
        if any(s in low for s in skip):
            continue
        if ":" in name or name.isdigit():
            continue
        if len(name) < 4:
            continue
        if "_" in name and " " not in name:
            continue
        if name in out:
            continue
        out.append(name)
        if len(out) >= n:
            break
    return out


def render_dossier(title: str, kind: str, hits: list[dict], extra: str = "") -> str:
    eid = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "entity"
    lines = [
        f"# {title}",
        "",
        f"kind: {kind}",
        f"entity_id: ENTITY-{eid}",
        f"stamped: {utc()}",
        "source: kg.jsonl (banned silos excluded). No invented facts.",
        "",
    ]
    if extra:
        lines.append(extra)
        lines.append("")
    if not hits:
        lines.append("_No sourced triples for this label. Do not invent._")
        return "\n".join(lines) + "\n"
    rels: defaultdict[str, list[str]] = defaultdict(list)
    for h in hits:
        s = str(h.get("s") or "?").strip()
        r = str(h.get("r") or "?").strip()
        o = str(h.get("o") or "?").strip()
        rels[r].append(f"{s} → {o}")
    lines.append("## Sourced relations")
    lines.append("")
    n = 0
    for rel, items in list(rels.items())[:12]:
        lines.append(f"**{rel}**")
        for it in items[:8]:
            lines.append(f"- {it}")
            n += 1
            if n >= 28:
                break
        if n >= 28:
            break
        lines.append("")
    lines.append(f"_{len(hits)} triples matched; truncated for 9B._")
    text = "\n".join(lines) + "\n"
    # hard cap ~600 tokens ≈ 2400 chars
    if len(text) > 2400:
        text = text[:2300].rsplit("\n", 1)[0] + "\n\n_truncated._\n"
    return text


def playbook_excerpt(path: str, limit: int = 520) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    lines = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("# PLAYBOOK") or ln.startswith("# STACK LAW"):
            continue
        lines.append(ln)
        if len("\n".join(lines)) >= limit:
            break
    blob = "\n".join(lines).strip()
    return blob[:limit]


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    return s[:60] or "entity"


def main() -> int:
    rows = load_triples()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        if old.name != "00-INDEX.md":
            try:
                old.unlink()
            except OSError:
                pass
    written = []
    for name, needles in FAMILY:
        hits = cluster_hits(rows, needles)
        body = render_dossier(name, "family", hits, extra="Family = merge-only. Do not invent names.")
        path = OUT / f"ENTITY-{slug(name)}.md"
        path.write_text(body, encoding="utf-8")
        written.append((name, str(path), len(hits), len(body.split())))
    for name, needles in DOMAINS:
        hits = cluster_hits(rows, needles)
        extra = ""
        play = {
            "Booksbloom": r"D:\PhronesisVault\Playbooks\PLAYBOOK_BOOKSBLOOM.md",
            "FLL-SPIKE-Prime": r"D:\PhronesisVault\Playbooks\PLAYBOOK_FLL_ROBOTICS.md",
            "Albion-Online": r"D:\PhronesisVault\Playbooks\PLAYBOOK_ALBION_ECONOMY.md",
            "OptiPlex-Sovereign-AI": r"D:\HermesData\STACK-LAW.md",
        }.get(name)
        if play:
            extra = f"Playbook: `{play}`"
            excerpt = playbook_excerpt(play)
            if excerpt:
                extra = extra + "\n\n## Playbook excerpt (sourced)\n\n" + excerpt
        if name == "OptiPlex-Sovereign-AI":
            extra = (
                extra
                + "\n\nSourced stack (STACK-LAW + MEMORY + primer; no invented specs):\n"
                "- Hardware: OptiPlex 7090, 128 GB RAM, RTX 3060 12 GB (one GPU tenant).\n"
                "- CORE ports: :8642 gateway, :8091 sovereign proxy, :8090 Qwythos 9B 128k. Never tear down :8090.\n"
                "- Optional: :9119 dash (not Discord-core), :8092 hybrid OFF unless Jeff names Swap8090.\n"
                "- Weights only on `D:\\PhronesisModels`. C: watch ~20 GB free; kitchen GREEN unless named heal.\n"
                "- Tools: vault_search, service_manager, system_telemetry. Restart never targets :8090.\n"
                "- Primer: `D:\\HermesData\\state\\prompts\\qwythos_system_primer.md`"
            )
        body = render_dossier(name, "domain", hits, extra=extra)
        path = OUT / f"ENTITY-{slug(name)}.md"
        path.write_text(body, encoding="utf-8")
        written.append((name, str(path), len(hits), len(body.split())))
    hubs = top_hubs(rows, n=8)
    named = {n.lower() for n, _ in FAMILY + DOMAINS}
    extra_n = 0
    for hub in hubs:
        if any(x in hub.lower() for x in named):
            continue
        hits = cluster_hits(rows, (hub.lower()[:24],), cap=24)
        if len(hits) < 3:
            continue
        body = render_dossier(hub, "cluster", hits)
        path = OUT / f"ENTITY-{slug(hub)}.md"
        path.write_text(body, encoding="utf-8")
        written.append((hub, str(path), len(hits), len(body.split())))
        extra_n += 1
        if extra_n >= 8:
            break
    idx = ["# Entity dossiers (pre-baked for 9B)", "", f"stamped={utc()} n={len(written)}", ""]
    idx.append("| Entity | Hits | Words | File |")
    idx.append("|---|---|---|---|")
    for name, path, hits, words in written:
        idx.append(f"| {name} | {hits} | {words} | `{Path(path).name}` |")
    INDEX.write_text("\n".join(idx) + "\n", encoding="utf-8")
    print(f"DISTILL n={len(written)} out={OUT}")
    for name, path, hits, words in written:
        print(f"  {name} hits={hits} words={words}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
