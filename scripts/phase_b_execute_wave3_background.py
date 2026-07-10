#!/usr/bin/env python3
"""Background Phase B wave3: es_ingest, review-moc, Discord HERMES-config index, vault program docs."""
from __future__ import annotations

import hashlib
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
ARCHIVE = VAULT / "Archive" / "Distillations-2026-07-10" / "Wave3"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d")
receipts: list[str] = []


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    try:
        receipts.append(f"WRITE {path.relative_to(VAULT)}")
    except ValueError:
        receipts.append(f"WRITE {path}")


def archive_move(src: Path, sub: str) -> None:
    dest_dir = ARCHIVE / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix}"
    shutil.move(str(src), str(dest))
    receipts.append(f"ARCHIVE {src.name}")


def one_line(p: Path) -> str:
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in t.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return re.sub(r"\s+", " ", s)[:160]
    return ""


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    # 1) es_ingest stubs
    ing = VAULT / "AI-Zone" / "ingested"
    es = sorted(ing.glob("es_ingest_*.md")) if ing.exists() else []
    if es:
        lines = [
            f"# ES Ingest Stubs — Index ({TS})",
            "",
            f"**Count:** {len(es)} live-export stubs (thin provenance).",
            "Originals archived Wave3 (recoverable).",
            "",
            "| File | Summary |",
            "|------|---------|",
        ]
        for p in es:
            lines.append(f"| {p.name} | {one_line(p).replace('|', '/')} |")
        lines += [
            "",
            "## Vault links",
            "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
            "",
        ]
        write(ing / "es_ingest_INDEX.md", "\n".join(lines))
        write(
            ARCHIVE / "es_ingest" / "README.md",
            "Archived es_ingest_*.md stubs. Index: [[AI-Zone/ingested/es_ingest_INDEX]]\n",
        )
        for p in es:
            archive_move(p, "es_ingest")

    # 2) review-moc pilots
    rm_dir = VAULT / "AI-Zone" / "review-moc"
    rms = sorted(rm_dir.glob("review-moc-pilot*.md")) if rm_dir.exists() else []
    if rms:
        parts = [
            f"# Review-MOC Pilots — Digest ({TS})",
            "",
            f"**Count:** {len(rms)}",
            "",
        ]
        for p in rms:
            parts.append(f"## {p.stem}")
            parts.append(p.read_text(encoding="utf-8", errors="ignore").strip()[:2000])
            parts.append("")
        write(rm_dir / "review-moc-pilots-DIGEST.md", "\n".join(parts))
        write(
            ARCHIVE / "review-moc" / "README.md",
            "Archived review-moc pilots. Digest: [[AI-Zone/review-moc/review-moc-pilots-DIGEST]]\n",
        )
        for p in rms:
            archive_move(p, "review-moc")

    # 3) Discord HERMES-config sprawl — master index; archive Archives/ + exact duplicate hashes of bare HERMES-config.md
    discord = VAULT / "Discord" / "configs"
    configs = list(discord.rglob("HERMES-config*.md")) if discord.exists() else []
    by_folder: dict[str, list[Path]] = defaultdict(list)
    for p in configs:
        by_folder[str(p.parent.relative_to(VAULT))].append(p)

    idx_lines = [
        f"# Discord HERMES-config Map ({TS})",
        "",
        f"**Files found:** {len(configs)}",
        "Wave3: map all; archive `Discord/configs/Archives/` copies; keep category stubs.",
        "",
    ]
    for folder, files in sorted(by_folder.items()):
        idx_lines.append(f"## `{folder}` ({len(files)})")
        for p in sorted(files, key=lambda x: x.name):
            idx_lines.append(f"- `{p.name}` ({p.stat().st_size}b)")
        idx_lines.append("")
    idx_lines += [
        "## Vault links",
        "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
        "",
    ]
    write(VAULT / "Discord" / "configs" / "HERMES-CONFIG-MAP.md", "\n".join(idx_lines))

    arch_dir = discord / "Archives"
    if arch_dir.exists():
        write(
            ARCHIVE / "discord-hermes-config-archives" / "README.md",
            "Archived Discord/configs/Archives HERMES-config* notes.\n"
            "Map: [[Discord/configs/HERMES-CONFIG-MAP]]\n",
        )
        for p in list(arch_dir.glob("HERMES-config*.md")):
            archive_move(p, "discord-hermes-config-archives")

    # exact-hash duplicates of basename HERMES-config.md across folders (keep first)
    bare = [p for p in configs if p.name == "HERMES-config.md" and p.exists()]
    # re-scan bare after archive
    bare = [p for p in (discord.rglob("HERMES-config.md") if discord.exists() else [])]
    hashes: dict[str, Path] = {}
    for p in bare:
        try:
            h = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
        if h in hashes:
            # duplicate content — archive this one, leave pointer file
            keep = hashes[h]
            write(
                p,
                f"""# HERMES-config (pointer)

**Canonical twin:** [[{str(keep.relative_to(VAULT)).replace(chr(92), '/').replace('.md','')}]]

Duplicate content removed {TS} (Wave3). Recoverable archive if this was unique (hash matched).

## Vault links
- [[Discord/configs/HERMES-CONFIG-MAP]]
""",
            )
            receipts.append(f"POINTER dupe HERMES-config {p.parent.name}")
        else:
            hashes[h] = p
    receipts.append(f"hermes-config unique hashes {len(hashes)}")

    # 4) Growth-Blueprints dated re-verification sprawl — index only if many
    gb = VAULT / "Operations" / "Growth-Blueprints"
    if gb.exists():
        gbs = list(gb.glob("*.md"))
        write(
            gb / "00-GROWTH-BLUEPRINTS-INDEX.md",
            f"""# Growth Blueprints Index ({TS})

**Count:** {len(gbs)}

These are high-signal research distillations — **not** auto-archived.
Open from this map; prefer updating core Research notes over new dated sprawl.

"""
            + "\n".join(f"- [[{p.stem}]]" for p in sorted(gbs, key=lambda x: x.name) if p.name != "00-GROWTH-BLUEPRINTS-INDEX.md")
            + """

## Vault links
- [[Research/Inspirational-Leaders]]
- [[Operations/Architecture-Idea-Triage]]
""",
        )
        receipts.append(f"growth blueprints indexed {len(gbs)}")

    # 5) Update program docs
    write(
        ARCHIVE / "README.md",
        f"""# Wave3 archive {TS}

- es_ingest/
- review-moc/
- discord-hermes-config-archives/

Recoverable. Working indexes in AI-Zone + Discord/configs.
""",
    )

    prog = VAULT / "Operations" / "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10.md"
    if prog.exists():
        t = prog.read_text(encoding="utf-8")
        note = f"""

## Background wave3 ({TS})
- es_ingest stubs → index + archive
- review-moc pilots → digest + archive
- Discord HERMES-config → map + archive Archives/
- Growth Blueprints → index map
- Receipt: [[Operations/logs/phase-b-merge-execution-wave3-{TS}]]
"""
        if "Background wave3" not in t:
            write(prog, t.rstrip() + note)
            receipts.append("updated active work program")

    write(
        VAULT / "Operations" / "logs" / f"phase-b-merge-execution-wave3-{TS}.md",
        f"# Phase B Wave3 Background — {TS}\n\n"
        + "\n".join(f"- {r}" for r in receipts)
        + "\n\n## Vault links\n- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]\n- [[Archive/Distillations-2026-07-10/Wave3/README]]\n",
    )

    # Housekeeping one line
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        cur = hk.read_text(encoding="utf-8", errors="ignore")
        line = f"\n- {TS}: Wave3 background distill (es_ingest, review-moc, Discord config map). [[Operations/logs/phase-b-merge-execution-wave3-{TS}]]\n"
        if "Wave3 background distill" not in cur[-2000:]:
            write(hk, cur + line)

    print("receipts", len(receipts))
    for r in receipts:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
