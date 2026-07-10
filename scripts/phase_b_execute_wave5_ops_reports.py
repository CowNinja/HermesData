#!/usr/bin/env python3
"""Wave5: Operations dated micro-reports + near-dup launch notes → digests + archive."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
OPS = VAULT / "Operations"
ARCHIVE = VAULT / "Archive" / "Distillations-2026-07-10" / "Wave5"
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
    if not src.exists():
        return
    dest_dir = ARCHIVE / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix}"
    shutil.move(str(src), str(dest))
    receipts.append(f"ARCHIVE {src.name}")


def one_line(p: Path, n: int = 160) -> str:
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in t.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return re.sub(r"\s+", " ", s)[:n]
    return ""


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    # --- A) 2026-06-19 report swarm ---
    june19 = []
    for p in OPS.glob("*.md"):
        name = p.name
        if "2026-06-19" in name or name.endswith("2026-06-19.md"):
            # keep the master index if it's the index itself
            if name in ("Session-Reports-2026-06-19-Index.md",):
                continue
            june19.append(p)
    # also MicroStep / reports that are clearly same day swarm without date in name? skip
    if june19:
        lines = [
            f"# Session / Micro-Reports — 2026-06-19 MASTER ({TS})",
            "",
            f"**Count archived:** {len(june19)}",
            "These were same-day micro-step execution reports. One master map replaces the swarm.",
            f"**Archive:** `Archive/Distillations-2026-07-10/Wave5/june19-reports/`",
            "",
            "| File | One-line |",
            "|------|----------|",
        ]
        for p in sorted(june19, key=lambda x: x.name.lower()):
            lines.append(f"| {p.name} | {one_line(p).replace('|', '/')} |")
        lines += [
            "",
            "## Distilled lesson",
            "- Prefer one living STATUS + thin receipts over N dated full reports.",
            "- Phase/micro work should append to a single run log when possible.",
            "",
            "## Still living (not in this swarm)",
            "- [[Operations/STATUS]]",
            "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
            "- [[docs/agent-coordination/STATUS]]",
            "",
            "## Vault links",
            "- [[Operations/Session-Reports-2026-06-19-Index]]",
            "",
        ]
        write(OPS / "Session-Reports-2026-06-19-MASTER.md", "\n".join(lines))
        # refresh old index as pointer
        write(
            OPS / "Session-Reports-2026-06-19-Index.md",
            f"""# Session Reports 2026-06-19 — Index (pointer)

**Canonical master:** [[Operations/Session-Reports-2026-06-19-MASTER]]

Updated {TS} Wave5. Individual reports archived (recoverable).
""",
        )
        write(
            ARCHIVE / "june19-reports" / "README.md",
            "Archived 2026-06-19 Operations micro-reports.\n"
            "Master: [[Operations/Session-Reports-2026-06-19-MASTER]]\n",
        )
        for p in june19:
            archive_move(p, "june19-reports")

    # --- B) Near-dup launch / FIFO pairs ---
    pairs = [
        (
            "Llama-Server-Launch-Report-2026-06-19.md",
            "LlamaServer-Launch-Report-2026-06-19.md",
            "Llama-Server-Launch",
        ),
        (
            "Sovereign-FIFO-Queue-Analysis-2026-07-06.md",
            "Sovereign-Router-FIFO-Analysis-2026-07-06.md",
            "Sovereign-FIFO",
        ),
    ]
    for a, b, label in pairs:
        pa, pb = OPS / a, OPS / b
        # may already be archived in june19
        existing = [p for p in (pa, pb) if p.exists()]
        if len(existing) >= 1:
            parts = [f"# {label} — Combined Digest ({TS})", ""]
            for p in existing:
                parts.append(f"## {p.stem}")
                parts.append(p.read_text(encoding="utf-8", errors="ignore").strip()[:3000])
                parts.append("")
            write(OPS / f"{label}-DIGEST.md", "\n".join(parts))
            for p in existing:
                archive_move(p, "near-dup-pairs")

    # --- C) VaultWalker dated status clutter (keep safe gardener + log review + hybrid) ---
    keep_vw = {
        "VaultWalker-Safe-Gardener-2026-07-10.md",
        "VaultWalker-Log-Review-and-Sanitize-Aftermath-2026-07-10.md",
        "VaultWalker-EndToEnd-Review-2026-07-08.md",
        "Hybrid-Grok-Driver-Qwythos-Grunt-Architecture-2026-07-10.md",
    }
    vw = [
        p
        for p in OPS.glob("VaultWalker-*.md")
        if p.name not in keep_vw
    ]
    if vw:
        lines = [
            f"# VaultWalker Status Snapshots — Index ({TS})",
            "",
            "Living docs kept separately (Safe Gardener, Log Review, EndToEnd).",
            f"**Archived snapshots:** {len(vw)}",
            "",
            "| File | One-line |",
            "|------|----------|",
        ]
        for p in sorted(vw, key=lambda x: x.name):
            lines.append(f"| {p.name} | {one_line(p).replace('|', '/')} |")
        lines += [
            "",
            "## Keep open",
            "- [[Operations/VaultWalker-Safe-Gardener-2026-07-10]]",
            "- [[Operations/VaultWalker-Log-Review-and-Sanitize-Aftermath-2026-07-10]]",
            "",
        ]
        write(OPS / "VaultWalker-Snapshots-INDEX.md", "\n".join(lines))
        for p in vw:
            archive_move(p, "vaultwalker-snapshots")

    # --- D) Ollama / MicroStep2 / Tiny-Classifier clusters if still present ---
    clusters = {
        "ollama": list(OPS.glob("Ollama-*.md")),
        "microstep2": list(OPS.glob("MicroStep2-*.md")),
        "tiny-classifier": list(OPS.glob("Tiny-Classifier-*.md")),
    }
    for label, files in clusters.items():
        files = [p for p in files if p.exists()]
        if len(files) < 2:
            continue
        parts = [f"# {label} — Digest ({TS})", ""]
        for p in sorted(files, key=lambda x: x.name):
            parts.append(f"## {p.stem}")
            parts.append(p.read_text(encoding="utf-8", errors="ignore").strip()[:2500])
            parts.append("")
        write(OPS / f"{label}-DIGEST.md", "\n".join(parts))
        for p in files:
            archive_move(p, f"cluster-{label}")

    write(
        ARCHIVE / "README.md",
        f"# Wave5 {TS}\n\njune19-reports · near-dup-pairs · vaultwalker-snapshots · ollama/microstep/tiny clusters\n",
    )
    write(
        OPS / "logs" / f"phase-b-merge-execution-wave5-{TS}.md",
        f"# Phase B Wave5 — {TS}\n\n" + "\n".join(f"- {r}" for r in receipts) + "\n",
    )
    prog = OPS / "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10.md"
    if prog.exists():
        t = prog.read_text(encoding="utf-8")
        if "Background wave5" not in t:
            write(
                prog,
                t.rstrip()
                + f"\n\n## Background wave5 ({TS})\n"
                "- June-19 micro-report swarm → MASTER + archive\n"
                "- Near-dup launch/FIFO · VaultWalker snapshots · Ollama/MicroStep/Tiny digests\n"
                f"- Receipt: [[Operations/logs/phase-b-merge-execution-wave5-{TS}]]\n",
            )
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        cur = hk.read_text(encoding="utf-8", errors="ignore")
        if "Wave5" not in cur[-2000:]:
            write(
                hk,
                cur
                + f"\n- {TS}: Wave5 Operations micro-report distill. [[Operations/logs/phase-b-merge-execution-wave5-{TS}]]\n",
            )

    print("receipts", len(receipts))
    for r in receipts:
        print(r)
    print("ops md remaining", len(list(OPS.glob("*.md"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
