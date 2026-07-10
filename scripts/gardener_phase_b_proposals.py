#!/usr/bin/env python3
"""Gardener Phase B — PROPOSAL ONLY (no moves, merges, or archives).

Grand vision steps 3–5 without execution:
  cluster duplicate ideas → propose distill into singular MD → propose recoverable archive

Default roots: PhronesisVault/Operations (+ optional Research, docs).
Uses local heuristics first; optional --grunt for Qwythos labels via grunt_local.

Outputs:
  D:\\PhronesisVault\\Operations\\logs\\gardener-phase-b-latest.md
  D:\\HermesData\\logs\\gardener-phase-b-latest.json

Cron: no_agent, deliver local.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

VAULT = Path(r"D:\PhronesisVault")
HERMES = Path(r"D:\HermesData")
OUT_MD = VAULT / "Operations" / "logs" / "gardener-phase-b-latest.md"
OUT_JSON = HERMES / "logs" / "gardener-phase-b-latest.json"
OUT_JSONL = HERMES / "logs" / "gardener-phase-b-runs.jsonl"

SKIP_DIR_PARTS = {
    ".git", ".obsidian", ".smart-env", ".trash", "node_modules", "__pycache__",
    "Archive", "archives", "tmp", "cache", "venv", ".venv",
}
SKIP_NAME_PREFIX = ("00-INDEX", "INDEX.md", "Resurfaced-Ideas")


def should_skip_dir(p: Path) -> bool:
    low = {x.lower() for x in p.parts}
    return bool(low & {s.lower() for s in SKIP_DIR_PARTS})


def stem_key(name: str) -> str:
    s = Path(name).stem.lower()
    s = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", s)
    s = re.sub(r"\d{8}", "DATE", s)
    s = re.sub(r"[-_]v?\d+(\.\d+)*$", "", s)
    s = re.sub(r"[-_]+", "-", s).strip("-")
    return s


def link_count(text: str) -> int:
    return text.count("[[") + len(re.findall(r"\]\([^)]+\)", text))


def scan_mds(roots: List[Path], max_files: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            if should_skip_dir(p.parent):
                continue
            if p.name.startswith("00-INDEX") or p.name == "INDEX.md":
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > 2_000_000:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            age_days = (datetime.now().timestamp() - st.st_mtime) / 86400.0
            rows.append({
                "path": str(p),
                "rel": str(p.relative_to(VAULT)) if str(p).startswith(str(VAULT)) else str(p),
                "name": p.name,
                "stem": stem_key(p.name),
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "age_days": round(age_days, 1),
                "links": link_count(text),
                "chars": len(text),
                "preview": re.sub(r"\s+", " ", text[:240]).strip(),
            })
            if len(rows) >= max_files:
                return rows
    return rows


INTENTIONAL_DUAL_STEMS = {
    "status",
    "orchestrator-pilot-run-log",
}

def cluster_stems(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["stem"]].append(r)
    clusters = []
    for stem, items in by.items():
        if len(items) < 2:
            continue
        if stem in {"index", "readme", "log", "notes", "untitled", "date"}:
            continue
        if stem in INTENTIONAL_DUAL_STEMS:
            continue
        items_sorted = sorted(items, key=lambda x: (-x["links"], -x["size"], x["age_days"]))
        clusters.append({
            "stem": stem,
            "count": len(items),
            "action": "distill_merge_propose",
            "reason": f"{len(items)} files share stem pattern — candidate singular MD",
            "keep_candidate": items_sorted[0]["rel"],
            "merge_from": [x["rel"] for x in items_sorted[1:6]],
            "all": [x["rel"] for x in items_sorted[:12]],
        })
    clusters.sort(key=lambda c: -c["count"])
    return clusters


def archive_candidates(rows: List[Dict[str, Any]], stale_days: int, limit: int) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        rel_l = r["rel"].lower()
        if "archive" in rel_l or "housekeeping" in rel_l:
            continue
        # stale + low links + not tiny stubs only
        if r["age_days"] >= stale_days and r["links"] < 2 and r["chars"] > 400:
            out.append({
                "action": "archive_propose",
                "rel": r["rel"],
                "age_days": r["age_days"],
                "links": r["links"],
                "reason": f"~{r['age_days']}d old, {r['links']} wikilinks — low graph signal",
            })
    out.sort(key=lambda x: (-x["age_days"], x["links"]))
    return out[:limit]


def resurface_candidates(rows: List[Dict[str, Any]], stale_days: int, limit: int) -> List[Dict[str, Any]]:
    """Forgotten projects: old but still substantial (worth re-reading)."""
    out = []
    for r in rows:
        if r["age_days"] < stale_days:
            continue
        if r["chars"] < 800:
            continue
        score = min(r["chars"] / 2000.0, 5) + (2 if r["links"] == 0 else 0)
        if any(k in r["name"].lower() for k in ("plan", "roadmap", "vision", "architecture", "proposal", "phase")):
            score += 2
        out.append({
            "action": "resurface_propose",
            "rel": r["rel"],
            "age_days": r["age_days"],
            "links": r["links"],
            "score": round(score, 2),
            "reason": "stale substantial note — possible forgotten project/idea",
            "preview": r["preview"][:160],
        })
    out.sort(key=lambda x: (-x["score"], -x["age_days"]))
    return out[:limit]


def optional_grunt(paths: List[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Best-effort local labels; never fails the run."""
    results = []
    grunt = HERMES / "scripts" / "grunt_local.py"
    if not grunt.exists():
        return results
    for rel in paths[:limit]:
        p = VAULT / rel if not Path(rel).is_absolute() else Path(rel)
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")[:1200]
        except OSError:
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(grunt), "classify", "--text", text[:900]],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(HERMES),
            )
            results.append({
                "rel": rel,
                "exit": proc.returncode,
                "out": ((proc.stdout or "") + (proc.stderr or ""))[-400:],
            })
        except Exception as e:
            results.append({"rel": rel, "error": str(e)[:120]})
    return results


def render_md(payload: Dict[str, Any]) -> str:
    lines = [
        f"# Gardener Phase B Proposals — {payload.get('ts', '')}",
        "",
        "**Mode: PROPOSAL ONLY** — no merges, moves, or deletes executed.",
        f"Roots: {', '.join(payload.get('roots') or [])}",
        f"Files scanned: {payload.get('scanned')}",
        "",
        "## Summary",
        f"- Distill/merge clusters: **{len(payload.get('distill_clusters') or [])}**",
        f"- Archive candidates: **{len(payload.get('archive_candidates') or [])}**",
        f"- Resurface (forgotten) candidates: **{len(payload.get('resurface_candidates') or [])}**",
        f"- Grunt labels: {len(payload.get('grunt') or [])}",
        "",
        "Aligned with: [[Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10]]",
        "Autonomy: [[Operations/Autonomy-Pathway-Dreamer-Worker-2026-07-10]]",
        "",
        "## Top distill/merge clusters",
        "",
    ]
    for c in (payload.get("distill_clusters") or [])[:15]:
        lines.append(f"### `{c['stem']}` (n={c['count']})")
        lines.append(f"- **Keep candidate:** `{c['keep_candidate']}`")
        lines.append(f"- **Merge from:**")
        for m in c.get("merge_from") or []:
            lines.append(f"  - `{m}`")
        lines.append(f"- Reason: {c['reason']}")
        lines.append("")
    lines += ["## Archive proposals (recoverable — do not auto-run)", ""]
    for a in (payload.get("archive_candidates") or [])[:20]:
        lines.append(f"- `{a['rel']}` — {a['reason']}")
    lines += ["", "## Resurface / forgotten ideas", ""]
    for r in (payload.get("resurface_candidates") or [])[:20]:
        lines.append(f"- `{r['rel']}` (~{r['age_days']}d, links={r['links']}, score={r['score']})")
        if r.get("preview"):
            lines.append(f"  - _{r['preview']}_")
    if payload.get("grunt"):
        lines += ["", "## Optional local grunt labels", ""]
        for g in payload["grunt"]:
            lines.append(f"- `{g.get('rel')}`: ```{(g.get('out') or g.get('error') or '')[:300]}```")
    lines += [
        "",
        "## Next human gates",
        "1. Pick 1–3 distill clusters → approve merge text",
        "2. Pick archive batch → move to Archive/ with pointer from hub",
        "3. Open 1 resurfaced forgotten project and decide: revive / distill / archive",
        "",
        "*Phase B never executes irreversible steps.*",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="*", default=["Operations", "Research", "docs"])
    ap.add_argument("--max-files", type=int, default=4000)
    ap.add_argument("--stale-days", type=int, default=45)
    ap.add_argument("--grunt", action="store_true", help="Label top resurface candidates via grunt_local")
    args = ap.parse_args()

    roots = []
    for r in args.roots:
        p = Path(r)
        if not p.is_absolute():
            p = VAULT / r
        roots.append(p)

    rows = scan_mds(roots, args.max_files)
    distill = cluster_stems(rows)[:40]
    archive = archive_candidates(rows, args.stale_days, 40)
    resurface = resurface_candidates(rows, args.stale_days, 30)
    grunt = optional_grunt([x["rel"] for x in resurface], 5) if args.grunt else []

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "proposal_only",
        "roots": [str(r) for r in roots],
        "scanned": len(rows),
        "distill_clusters": distill,
        "archive_candidates": archive,
        "resurface_candidates": resurface,
        "grunt": grunt,
        "version": "gardener_phase_b/1.0",
    }

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with OUT_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": payload["ts"],
            "scanned": payload["scanned"],
            "distill": len(distill),
            "archive": len(archive),
            "resurface": len(resurface),
        }) + "\n")

    _refresh_indexes()
    print(
        f"PhaseB proposals: scanned={len(rows)} distill_clusters={len(distill)} "
        f"archive={len(archive)} resurface={len(resurface)} -> {OUT_MD}"
    )
    return 0




def _refresh_indexes() -> None:
    try:
        import subprocess, sys
        from pathlib import Path as _P
        _p = _P(r"D:/HermesData/scripts/refresh_folder_indexes.py")
        if _p.is_file():
            subprocess.run([sys.executable, str(_p)], capture_output=True, text=True, timeout=120)
    except Exception:
        pass

if __name__ == "__main__":
    raise SystemExit(main())
