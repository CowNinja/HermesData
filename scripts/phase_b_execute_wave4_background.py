#!/usr/bin/env python3
"""Wave4: re-verification sprawl, review-moc batches, test logs — digest + recoverable archive."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(r"D:\PhronesisVault")
ARCHIVE = VAULT / "Archive" / "Distillations-2026-07-10" / "Wave4"
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


def one_line(p: Path, n: int = 180) -> str:
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in t.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return re.sub(r"\s+", " ", s)[:n]
    return ""


def series_index_archive(files: list[Path], index_path: Path, sub: str, title: str) -> None:
    if not files:
        return
    lines = [
        f"# {title} ({TS})",
        "",
        f"**Count:** {len(files)}",
        "Pattern: singular index + recoverable archive (no landfill glue).",
        f"**Archive:** `Archive/Distillations-2026-07-10/Wave4/{sub}/`",
        "",
        "| File | One-line |",
        "|------|----------|",
    ]
    for p in sorted(files, key=lambda x: x.name):
        lines.append(f"| {p.name} | {one_line(p).replace('|', '/')} |")
    lines += ["", "## Vault links", "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]", ""]
    write(index_path, "\n".join(lines))
    write(
        ARCHIVE / sub / "README.md",
        f"Archived from wave4. Index: [[{str(index_path.relative_to(VAULT)).replace(chr(92),'/').replace('.md','')}]]\n",
    )
    for p in files:
        archive_move(p, sub)


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    # 1) review-moc batch es_ingest
    rm = VAULT / "AI-Zone" / "review-moc"
    if rm.exists():
        files = list(rm.glob("review-moc-batch_es_ingest_*.md"))
        series_index_archive(
            files,
            rm / "review-moc-batch-es-ingest-INDEX.md",
            "review-moc-batch-es",
            "Review-MOC batch es_ingest — Index",
        )

    # 2) references re-verification sprawl (cron noise class)
    refs = VAULT / "references"
    if refs.exists():
        patterns = [
            ("phronesisvault-arxiv-*-reverification-confirmation.md", "reverify-arxiv"),
            ("phronesisvault-brian-roemmele-*-reverification-confirmation.md", "reverify-brian"),
            ("phronesisvault-brian-roemmele-*-reverification-execution.md", "reverify-brian-exec"),
            ("phronesisvault-brian-roemmele-*-6pm-reverification-confirmation.md", "reverify-brian-6pm"),
            ("phronesisvault-karpathy-*-reverification-confirmation.md", "reverify-karpathy"),
            ("phronesisvault-karpathy-*-continuation-reverification-confirmation.md", "reverify-karpathy-cont"),
        ]
        all_re = []
        for pat, sub in patterns:
            files = list(refs.glob(pat))
            all_re.extend(files)
        if all_re:
            # one master index then archive all
            lines = [
                f"# Re-Verification Cron Noise — Distilled Index ({TS})",
                "",
                "These were repetitive 'no-new' confirmation dumps. High-signal research stays in Growth-Blueprints / Research.",
                f"**Archived count:** {len(all_re)}",
                "",
                "| File | One-line |",
                "|------|----------|",
            ]
            for p in sorted(all_re, key=lambda x: x.name):
                lines.append(f"| {p.name} | {one_line(p).replace('|', '/')} |")
            lines += [
                "",
                "## Keep using",
                "- [[Operations/Growth-Blueprints/00-GROWTH-BLUEPRINTS-INDEX]]",
                "- [[Operations/Cron-Append-Policy]]",
                "",
            ]
            write(refs / "REVERIFICATION-NOISE-INDEX.md", "\n".join(lines))
            write(
                ARCHIVE / "reverification-noise" / "README.md",
                "Archived repetitive re-verification confirmations.\n"
                "Index: [[references/REVERIFICATION-NOISE-INDEX]]\n",
            )
            for p in all_re:
                archive_move(p, "reverification-noise")

    # 3) tests/logs noise
    tlog = VAULT / "tests" / "logs"
    if tlog.exists():
        files = [p for p in tlog.glob("*.md") if p.is_file()]
        if files:
            series_index_archive(
                files,
                tlog / "TEST-LOGS-INDEX.md",
                "test-logs",
                "Test logs — Index",
            )

    # 4) program + housekeeping check-in
    write(
        ARCHIVE / "README.md",
        f"# Wave4 {TS}\n\nreview-moc-batch-es · reverification-noise · test-logs\nRecoverable.\n",
    )
    write(
        VAULT / "Operations" / "logs" / f"phase-b-merge-execution-wave4-{TS}.md",
        f"# Phase B Wave4 — {TS}\n\n"
        + "\n".join(f"- {r}" for r in receipts)
        + "\n\n## Vault links\n- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]\n",
    )
    prog = VAULT / "Operations" / "Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10.md"
    if prog.exists():
        t = prog.read_text(encoding="utf-8")
        note = f"\n\n## Background wave4 ({TS})\n- Re-verification cron noise → index + archive\n- review-moc es_ingest batches → index + archive\n- tests/logs → index + archive\n- Receipt: [[Operations/logs/phase-b-merge-execution-wave4-{TS}]]\n"
        if "Background wave4" not in t:
            write(prog, t.rstrip() + note)
    hk = VAULT / "Housekeeping.md"
    if hk.exists():
        cur = hk.read_text(encoding="utf-8", errors="ignore")
        line = f"\n- {TS}: Wave4 — re-verify noise + review-moc batches + test logs distilled. [[Operations/logs/phase-b-merge-execution-wave4-{TS}]]\n"
        if "Wave4 — re-verify" not in cur[-2500:]:
            write(hk, cur + line)

    print("receipts", len(receipts))
    for r in receipts[:40]:
        print(r)
    print("... total", len(receipts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
