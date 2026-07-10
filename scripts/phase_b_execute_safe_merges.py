#!/usr/bin/env python3
"""Phase B safe maximal merges: digests + recoverable archive (never raw glue landfill)."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OPS = VAULT / "Operations"
ARCHIVE = VAULT / "Archive" / "Distillations-2026-07-10"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d")
receipts: list[str] = []


def one_line_summary(p: Path, max_len: int = 140) -> str:
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "(unreadable)"
    for line in t.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("**Links") or s.startswith("---"):
            continue
        s = re.sub(r"\s+", " ", s)
        return s[:max_len]
    return "(no body)"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    try:
        receipts.append(f"WRITE {path.relative_to(VAULT)}")
    except ValueError:
        receipts.append(f"WRITE {path}")


def archive_move(src: Path, sub: str) -> Path:
    dest_dir = ARCHIVE / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix}"
    shutil.move(str(src), str(dest))
    receipts.append(f"ARCHIVE {src.name} -> {dest.relative_to(VAULT)}")
    return dest


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    # 1) Orchestrator pointer
    ops_orch = OPS / "Orchestrator-Pilot-Run-Log.md"
    docs_orch = VAULT / "docs" / "agent-coordination" / "Orchestrator-Pilot-Run-Log.md"
    if ops_orch.exists() and docs_orch.exists():
        write(
            ops_orch,
            """# Orchestrator Pilot Run Log — Operations Pointer

**Canonical (append here):** [[docs/agent-coordination/Orchestrator-Pilot-Run-Log]]

This Operations path is a **pointer only** (distilled 2026-07-10 Phase B).
Do not append new pilot runs here — use the docs canonical file.

**Parent:** [[Operations/Sovereign-Stack-Operations-Index]] · [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]

## Vault links
- [[docs/agent-coordination/Orchestrator-Pilot-Run-Log]]
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
""",
        )
        receipts.append("ORCHESTRATOR: ops pointer only; docs canonical kept intact")

    # 2) Memory-Delta rollup + archive
    mds = sorted(OPS.glob("Memory-Delta-*.md"))
    if mds:
        lines = [
            f"# Memory Delta Sessions — Distilled Rollup ({TS})",
            "",
            f"**Source count:** {len(mds)} session delta files from ~2026-06-18",
            "**Method:** singular rollup + recoverable archive (not one concatenated landfill)",
            f"**Archive:** `Archive/Distillations-2026-07-10/Memory-Deltas/`",
            "",
            "## Index",
            "",
            "| File | Size | One-line |",
            "|------|-----:|----------|",
        ]
        for p in mds:
            lines.append(
                f"| {p.name} | {p.stat().st_size} | {one_line_summary(p).replace('|', '/')} |"
            )
        lines += [
            "",
            "## Distilled lesson",
            "- Per-session delta files flooded Operations/; one index + archive preserves history.",
            "- Future: one living memory note + thin journal, not N session files.",
            "",
            "## Vault links",
            "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
            "- [[Archive/Distillations-2026-07-10/Memory-Deltas/README]]",
            "",
        ]
        write(OPS / "Memory-Delta-Sessions-ROLLUP-2026-06-18.md", "\n".join(lines))
        write(
            ARCHIVE / "Memory-Deltas" / "README.md",
            "# Archived Memory-Delta session files\n\n"
            f"Archived {TS} from Operations/ after rollup.\n"
            "Rollup: [[Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18]]\n"
            "Recoverable: move any file back to Operations/ if needed.\n",
        )
        for p in mds:
            archive_move(p, "Memory-Deltas")

    # 3) Daily distillation index + archive
    dds = sorted((OPS / "logs").glob("daily-distillation-*.md"))
    if dds:
        lines = [
            f"# Daily Distillation Log — Index ({TS})",
            "",
            f"**Count:** {len(dds)} dated logs",
            "Originals archived under Archive/Distillations-2026-07-10/Daily-Distillation/",
            "",
            "| Date file | Size | Summary |",
            "|-----------|-----:|---------|",
        ]
        for p in dds:
            lines.append(
                f"| {p.name} | {p.stat().st_size} | {one_line_summary(p).replace('|', '/')} |"
            )
        lines += [
            "",
            "## Policy",
            "Prefer one living log row over proliferating full dated dumps.",
            "See [[Operations/Cron-Append-Policy]].",
            "",
            "## Vault links",
            "- [[Operations/Cron-Append-Policy]]",
            "",
        ]
        write(OPS / "logs" / "daily-distillation-INDEX.md", "\n".join(lines))
        write(
            ARCHIVE / "Daily-Distillation" / "README.md",
            "# Archived daily-distillation-*.md\n\n"
            "Indexed at [[Operations/logs/daily-distillation-INDEX]]\nRecoverable.\n",
        )
        for p in dds:
            archive_move(p, "Daily-Distillation")

    # 4) Routing batches digest + archive
    batches = sorted(OPS.glob("Automated-Routing-Batch-*.md"))
    if batches:
        parts = [
            f"# Automated Routing Batches — Digest ({TS})",
            "",
            "**Batches:** " + ", ".join(p.stem for p in batches),
            "",
        ]
        for p in batches:
            t = p.read_text(encoding="utf-8", errors="ignore")
            parts.append(f"## {p.stem}")
            parts.append("")
            parts.append(t.strip()[:2500])
            parts.append("")
        parts += [
            "## Vault links",
            "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
            "",
        ]
        write(OPS / "Automated-Routing-Batches-DIGEST.md", "\n".join(parts))
        write(
            ARCHIVE / "Routing-Batches" / "README.md",
            "Archived routing batch notes. Digest: [[Operations/Automated-Routing-Batches-DIGEST]]\n",
        )
        for p in batches:
            archive_move(p, "Routing-Batches")

    # 5) Secrets batches
    secs = sorted(OPS.glob("Secrets-Proposals-Batch-*.md"))
    if secs:
        parts = [f"# Secrets Proposals Batches — Digest ({TS})", ""]
        for p in secs:
            parts.append(f"## {p.stem}")
            parts.append(p.read_text(encoding="utf-8", errors="ignore").strip()[:2000])
            parts.append("")
        parts += ["## Vault links", "- [[Operations/Automated-Routing-Batches-DIGEST]]", ""]
        write(OPS / "Secrets-Proposals-Batches-DIGEST.md", "\n".join(parts))
        write(
            ARCHIVE / "Secrets-Batches" / "README.md",
            "Archived secrets batch notes. Digest: [[Operations/Secrets-Proposals-Batches-DIGEST]]\n",
        )
        for p in secs:
            archive_move(p, "Secrets-Batches")

    # 6) Session handoffs
    hands = sorted(OPS.glob("Session-Handoff-*.md"))
    if hands:
        parts = [f"# Session Handoffs — Digest ({TS})", ""]
        for p in hands:
            parts.append(f"## {p.stem}")
            parts.append(p.read_text(encoding="utf-8", errors="ignore").strip()[:3000])
            parts.append("")
        write(OPS / "Session-Handoffs-DIGEST.md", "\n".join(parts))
        write(
            ARCHIVE / "Session-Handoffs" / "README.md",
            "Archived handoffs. Digest: [[Operations/Session-Handoffs-DIGEST]]\n",
        )
        for p in hands:
            archive_move(p, "Session-Handoffs")

    receipts.append("SKIP cron-append: Cron-Append-Policy forbids merge into one dump")

    write(
        ARCHIVE / "README.md",
        f"""# Distillations archive {TS}

Recoverable archive from Phase B (digest + move, not delete).

## Folders
- Memory-Deltas/
- Daily-Distillation/
- Routing-Batches/
- Secrets-Batches/
- Session-Handoffs/

## Rollups
- [[Operations/Memory-Delta-Sessions-ROLLUP-2026-06-18]]
- [[Operations/logs/daily-distillation-INDEX]]
- [[Operations/Automated-Routing-Batches-DIGEST]]
- [[Operations/Secrets-Proposals-Batches-DIGEST]]
- [[Operations/Session-Handoffs-DIGEST]]

Restore any file by moving it back from this folder.
""",
    )

    write(
        OPS / "logs" / f"phase-b-merge-execution-{TS}.md",
        f"""# Phase B Merge Execution Receipt — {TS}

## Why not raw-merge everything?
- Unique logs glued = landfill, lost provenance, broken links
- cron-append must stay thin dated files (policy)
- Orchestrator ops was already a mirror of docs canonical

## What we did (safe maximal)
Digest/rollup in Operations/ + recoverable archive under `Archive/Distillations-2026-07-10/`.

## Receipts
"""
        + "\n".join(f"- {r}" for r in receipts)
        + """

## Vault links
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
- [[Archive/Distillations-2026-07-10/README]]
""",
    )

    print("receipts", len(receipts))
    for r in receipts:
        print(r)
    for sub in sorted(ARCHIVE.iterdir()):
        if sub.is_dir():
            print("dir", sub.name, "files", len([x for x in sub.iterdir() if x.is_file()]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
