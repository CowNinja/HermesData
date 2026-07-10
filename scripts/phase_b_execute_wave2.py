#!/usr/bin/env python3
"""Phase B wave 2 — remaining clusters (first-principles, recoverable).

Rules:
- cron-append: INDEX digest of lines; archive old dated files (crons recreate new days)
- intentional dual paths (orchestrator, STATUS): clarify roles + links, do NOT glue
- dated receipts: digest + archive
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
import shutil

VAULT = Path(r"D:\PhronesisVault")
OPS = VAULT / "Operations"
ARCHIVE = VAULT / "Archive" / "Distillations-2026-07-10" / "Wave2"
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d")
receipts: list[str] = []


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


def cron_job_id_from_name(name: str) -> str | None:
    # 2026-06-27-da0150a51594.md
    m = re.match(r"^\d{4}-\d{2}-\d{2}-([a-f0-9]+)\.md$", name, re.I)
    return m.group(1) if m else None


def index_cron_job(job_id: str) -> None:
    ca = OPS / "logs" / "cron-append"
    files = sorted(ca.glob(f"*-{job_id}.md"))
    if not files:
        receipts.append(f"SKIP cron job {job_id}: no files")
        return
    lines = [
        f"# Cron Append Index — job `{job_id}` ({TS})",
        "",
        f"**Files:** {len(files)} dated thin logs (policy: one-line-ish per run).",
        "**Action:** singular index + archive dated files (recoverable). New cron days recreate.",
        f"**Archive:** `Archive/Distillations-2026-07-10/Wave2/cron-{job_id}/`",
        "",
        "## Timeline",
        "",
    ]
    for p in files:
        body = p.read_text(encoding="utf-8", errors="ignore").strip()
        body_one = re.sub(r"\s+", " ", body)[:500]
        lines.append(f"### {p.name}")
        lines.append(f"- {body_one}")
        lines.append("")
    lines += [
        "## Policy",
        "See [[Operations/Cron-Append-Policy]] — do not re-expand into full protocol dumps.",
        "",
        "## Vault links",
        "- [[Operations/Cron-Append-Policy]]",
        "- [[Operations/logs/cron-append/00-INDEX]]",
        "",
    ]
    write(OPS / "logs" / "cron-append" / f"INDEX-job-{job_id}.md", "\n".join(lines))
    write(
        ARCHIVE / f"cron-{job_id}" / "README.md",
        f"Archived thin cron-append files for job {job_id}.\n"
        f"Index: [[Operations/logs/cron-append/INDEX-job-{job_id}]]\nRecoverable.\n",
    )
    for p in files:
        archive_move(p, f"cron-{job_id}")


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    # --- Clusters 1,2,5: cron-append job series ---
    for job_id in ("da0150a51594", "31c154062810", "e7ca4cfe6cf9"):
        index_cron_job(job_id)

    # Master cron-append jobs index
    job_indexes = sorted((OPS / "logs" / "cron-append").glob("INDEX-job-*.md"))
    remaining = [
        p
        for p in (OPS / "logs" / "cron-append").glob("*.md")
        if not p.name.startswith("INDEX")
        and p.name not in ("00-INDEX.md", "INDEX.md")
        and cron_job_id_from_name(p.name)
    ]
    write(
        OPS / "logs" / "cron-append" / "CRON-APPEND-JOBS-INDEX.md",
        f"""# Cron Append Jobs — Master Index ({TS})

Thin logs by job id. Wave2 distilled series into per-job INDEX + archive.

## Job indexes
"""
        + "\n".join(f"- [[{p.stem}]]" for p in job_indexes)
        + f"""

## Remaining live dated files (not in wave2 job list)
{chr(10).join(f'- `{p.name}`' for p in remaining) or '- (none matching YYYY-MM-DD-jobid)'}

## Policy
[[Operations/Cron-Append-Policy]]

## Vault links
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
""",
    )
    receipts.append(f"cron remaining dated files: {len(remaining)}")

    # --- Cluster 3: orchestrator — intentional dual (already pointer) ---
    ops_orch = OPS / "Orchestrator-Pilot-Run-Log.md"
    if ops_orch.exists():
        t = ops_orch.read_text(encoding="utf-8", errors="ignore")
        if "pointer only" in t.lower() or "Canonical" in t:
            receipts.append("ORCHESTRATOR: intentional dual OK (ops pointer / docs canonical) — no further merge")
        else:
            receipts.append("ORCHESTRATOR: unexpected content — left untouched")

    # --- Cluster 4: STATUS — different domains; cross-link, don't glue ---
    ops_status = OPS / "STATUS.md"
    docs_status = VAULT / "docs" / "agent-coordination" / "STATUS.md"
    if ops_status.exists() and docs_status.exists():
        ops_body = ops_status.read_text(encoding="utf-8", errors="ignore")
        # Keep stack status content; add clear role banner if missing
        if "Role: Stack / RP pipeline" not in ops_body:
            banner = f"""# STATUS — Stack / Runtime (Operations)

**Role:** Phronesis host + RP/Comfy stack health (lean).  
**Not the same as** coordination live status: [[docs/agent-coordination/STATUS]]  
**Updated distill note:** {TS} Phase B wave2 — dual STATUS files kept on purpose (separation of concerns).

---

"""
            # strip old H1 if present
            rest = ops_body
            if rest.lstrip().startswith("#"):
                rest = "\n".join(rest.splitlines()[1:]).lstrip()
            write(
                ops_status,
                banner
                + rest
                + """

## Vault links
- [[docs/agent-coordination/STATUS]]
- [[docs/agent-coordination/GROK-HERMES-MASTER-PLAN]]
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
""",
            )
        # append note to docs status footer if no link to ops
        docs_body = docs_status.read_text(encoding="utf-8", errors="ignore")
        if "Operations/STATUS" not in docs_body and "Stack / Runtime" not in docs_body:
            write(
                docs_status,
                docs_body.rstrip()
                + f"""

---

## Related (Phase B wave2 {TS})
- **Stack/runtime STATUS (Operations):** [[Operations/STATUS]] — host, Comfy, RP pipeline (separate concern)
- Do not merge these two STATUS files; different audiences.

## Vault links
- [[Operations/STATUS]]
""",
            )
        receipts.append("STATUS: kept dual with role separation + bidirectional links (no landfill glue)")

    # --- Cluster 6: Thread-Update-Receipt series ---
    coord = VAULT / "docs" / "agent-coordination"
    receipts_files = sorted(coord.glob("Thread-Update-Receipt-*.md"))
    if receipts_files:
        parts = [
            f"# Thread Update Receipts — Digest ({TS})",
            "",
            f"**Count:** {len(receipts_files)}",
            "Originals archived Wave2 (recoverable).",
            "",
        ]
        for p in receipts_files:
            parts.append(f"## {p.stem}")
            parts.append("")
            parts.append(p.read_text(encoding="utf-8", errors="ignore").strip()[:3500])
            parts.append("")
        parts += [
            "## Vault links",
            "- [[docs/agent-coordination/STATUS]]",
            "- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]",
            "",
        ]
        write(coord / "Thread-Update-Receipts-DIGEST.md", "\n".join(parts))
        write(
            ARCHIVE / "Thread-Receipts" / "README.md",
            "Archived Thread-Update-Receipt-*.md\n"
            "Digest: [[docs/agent-coordination/Thread-Update-Receipts-DIGEST]]\n",
        )
        for p in receipts_files:
            archive_move(p, "Thread-Receipts")

    # --- Bonus: light resurface queue (not archive research) ---
    resurface = [
        "Research/Forensic-Audit-HermesData-BACKUP-2026-06-12.md",
        "Research/Brian-Roemmele-Part-31-Category-Inventor-2026-06-14.md",
        "Research/Guardrails-for-Perpetual-Agents.md",
    ]
    write(
        OPS / "Resurface-Queue-Phase-B.md",
        f"""# Resurface Queue — Phase B ({TS})

Forgotten / stale **high-value** notes — do **not** auto-archive. Open when ready.

"""
        + "\n".join(f"- [[{r.replace('.md','')}]]" for r in resurface)
        + """

## Intent
Re-emerge ideas for the Machine (guardrails, Roemmele, forensics) — Jeff dreamer review.

## Vault links
- [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
""",
    )

    # Wave2 archive readme + execution receipt
    write(
        ARCHIVE / "README.md",
        f"""# Phase B Wave2 archive {TS}

- cron-*/ — archived thin cron-append dated files (indexes remain in Operations/logs/cron-append/)
- Thread-Receipts/ — archived thread update receipts

Recoverable. Indexes/digests live in vault working tree.
""",
    )
    write(
        OPS / "logs" / f"phase-b-merge-execution-wave2-{TS}.md",
        f"""# Phase B Wave2 Execution — {TS}

## First principles applied
1. **cron-append** = thin timeline → per-job INDEX + archive dates (not one megafile)
2. **STATUS dual** = different concerns (stack vs coordination) → link, don't glue
3. **Orchestrator dual** = already pointer/canonical → leave
4. **Thread receipts** = digest + archive
5. **Resurface** research = queue only (no archive)

## Receipts
"""
        + "\n".join(f"- {r}" for r in receipts)
        + """

## Vault links
- [[Operations/Active-Work-Program-Phase-B-Orchestrator-Insights-2026-07-10]]
- [[Archive/Distillations-2026-07-10/Wave2/README]]
- [[Operations/Resurface-Queue-Phase-B]]
""",
    )

    print("receipts", len(receipts))
    for r in receipts:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
