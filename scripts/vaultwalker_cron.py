#!/usr/bin/env python3
"""Safe VaultWalker cron entrypoint (travel-safe, expandable, feedback loop).

Design goals (Jeff grand vision):
- Walk silos, refresh per-folder indexes, resurface forgotten ideas
- Classify with local Qwythos via :8091 (inside vaultwalker)
- Default DRY-RUN: no moves / no destructive writes unless VAULTWALKER_LIVE=1
- Feedback scorecard after every run for adjustments
- Config-driven silos (data_silos.yaml) for infinite expandability

Usage:
  python vaultwalker_cron.py
  python vaultwalker_cron.py --silos PhronesisVault
  VAULTWALKER_LIVE=1 python vaultwalker_cron.py --live   # only when intentional

Cron: no_agent, deliver local, workdir D:\\HermesData
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(r"D:\HermesData")
WALKER = ROOT / "scripts" / "vaultwalker.py"
LOG_DIR = ROOT / "logs"
STATE_DIR = ROOT / "data" / "vaultwalker" / "state"
FEEDBACK_JSON = LOG_DIR / "vaultwalker-last-run.json"
FEEDBACK_JSONL = LOG_DIR / "vaultwalker-runs.jsonl"
FEEDBACK_MD = Path(r"D:\PhronesisVault\Operations\logs\vaultwalker-feedback-latest.md")
VISION_DOC = "Operations/Grand-Vision-Silo-Gardener-and-Hermes-Continuity-2026-07-10.md"


def evaluate_feedback(summary: Dict[str, Any], dry_run: bool, silos: List[str], rc: int) -> Dict[str, Any]:
    score = 100
    notes: List[str] = []
    risks: List[str] = []
    adjustments: List[str] = []

    notes.append("DRY-RUN safe mode" if dry_run else "LIVE mode (writes/moves possible)")
    if not dry_run:
        risks.append("live_writes")
        score -= 5

    if rc != 0:
        risks.append(f"exit_code_{rc}")
        score -= 20
        adjustments.append("Inspect daily_vaultwalker.log and vaultwalker-last-run.json")

    totals = {"indexes": 0, "resurfaced": 0, "moved": 0, "errors": 0, "evaluated": 0}
    for name, stats in summary.items():
        if not isinstance(stats, dict):
            continue
        if stats.get("error"):
            totals["errors"] += 1
            score -= 10
            risks.append(f"silo_error:{name}:{stats.get('error')}")
        totals["indexes"] += int(stats.get("per_folder_indexes") or 0)
        totals["resurfaced"] += int(stats.get("res_surfaced") or stats.get("res_stale_found") or 0)
        totals["moved"] += int(stats.get("reloc_moved") or 0)
        totals["evaluated"] += int(stats.get("reloc_evaluated") or 0)

    if totals["indexes"] == 0 and totals["errors"] == 0:
        notes.append("No index updates this cycle (incremental skip or light cycle) — ok if state fresh")
    else:
        notes.append(f"Index folders touched ~{totals['indexes']}")

    if totals["resurfaced"] > 0:
        notes.append(f"Forgotten-idea resurface candidates ~{totals['resurfaced']}")
        score += 5
    else:
        notes.append("No resurface candidates this cycle")
        adjustments.append("If this persists for days, run deep cycle or review STALE_DAYS")

    if totals["moved"] > 0:
        notes.append(f"Relocate actions counted: {totals['moved']} ({'planned' if dry_run else 'executed'})")
        if not dry_run:
            risks.append("files_moved")
            adjustments.append("Review Roleplay-Sandbox/data/misplaced_from_vaultwalker/relocation_audit.md")

    # Grand vision checklist
    vision = {
        "discover_index": totals["indexes"] >= 0,
        "understand_local": True,  # walker uses :8091 grunt path
        "resurface_forgotten": totals["resurfaced"] > 0,
        "safe_default_block": dry_run or totals["moved"] == 0,
        "expandable_silos": True,
        "feedback_loop": True,
    }
    if not vision["safe_default_block"]:
        adjustments.append("Keep dry-run while traveling; only LIVE with explicit env")

    score = max(0, min(100, score))
    return {
        "score": score,
        "notes": notes,
        "risks": risks,
        "suggested_adjustments": adjustments or ["none — continue dry-run monitoring"],
        "vision_checklist": vision,
        "totals": totals,
        "silos": silos,
        "dry_run": dry_run,
        "exit_code": rc,
        "ts": datetime.now(timezone.utc).isoformat(),
        "vision_doc": VISION_DOC,
    }


def render_md(payload: Dict[str, Any]) -> str:
    fb = payload.get("feedback") or {}
    lines = [
        f"# VaultWalker Feedback {fb.get('ts', '')}",
        "",
        f"**Score:** {fb.get('score', '?')}/100",
        f"**Mode:** {'DRY-RUN' if fb.get('dry_run') else 'LIVE'}",
        f"**Silos:** {', '.join(fb.get('silos') or [])}",
        f"**Exit:** {fb.get('exit_code')}",
        "",
        "## Notes",
    ]
    for n in fb.get("notes") or []:
        lines.append(f"- {n}")
    lines += ["", "## Risks"]
    risks = fb.get("risks") or []
    lines.append("- none" if not risks else "\n".join(f"- {r}" for r in risks))
    lines += ["", "## Suggested adjustments"]
    for a in fb.get("suggested_adjustments") or []:
        lines.append(f"- {a}")
    lines += ["", "## Totals", "```json", json.dumps(fb.get("totals") or {}, indent=2), "```", ""]
    lines.append(f"Grand vision: [[{VISION_DOC.replace('.md', '')}]]")
    lines.append("Autonomy path: [[Operations/Autonomy-Pathway-Dreamer-Worker-2026-07-10]]")
    lines.append("")
    return "\n".join(lines)


def parse_summary_from_stdout(stdout: str) -> Dict[str, Any]:
    """vaultwalker prints a final JSON blob with status complete."""
    text = stdout or ""
    # find last JSON object
    idx = text.rfind('{"status"')
    if idx < 0:
        idx = text.rfind('{\n  "status"')
    if idx < 0:
        return {"_raw_tail": text[-2000:], "_parse": "no_json"}
    blob = text[idx:]
    # trim after last closing brace balance
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # try progressive shrink
        for end in range(len(blob), 0, -1):
            try:
                return json.loads(blob[:end])
            except json.JSONDecodeError:
                continue
    return {"_raw_tail": text[-2000:], "_parse": "fail"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Safe VaultWalker cron runner")
    # no_agent cron cannot pass argv — defaults must finish under Hermes 240s script cap.
    # Full multi-silo walks (K: alone ~2.7k indexes) exceed 240s and mark the job error forever.
    default_silos = ["PhronesisVault"]
    env_silos = os.environ.get("VAULTWALKER_SILOS", "").strip()
    if env_silos:
        default_silos = [s.strip() for s in env_silos.split(",") if s.strip()]
    ap.add_argument("--silos", nargs="*", default=default_silos)
    ap.add_argument("--live", action="store_true", help="Allow live writes only if VAULTWALKER_LIVE=1")
    # Stay under Hermes no_agent script timeout (240s). Outer kill is 240s.
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("VAULTWALKER_TIMEOUT", "200")))
    # Daily 04:00 job: resurface forgotten ideas (cron-safe, no mass model calls).
    # Full model deep = manual / weekly green light only.
    ap.add_argument(
        "--cycle",
        choices=["auto", "light", "deep", "resurface"],
        default=os.environ.get("VAULTWALKER_CYCLE", "resurface").strip() or "resurface",
        help="Passed to vaultwalker --cycle (default resurface for daily cron)",
    )
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    live_env = os.environ.get("VAULTWALKER_LIVE", "").strip() == "1"
    dry = not (args.live and live_env)

    cmd = [sys.executable, str(WALKER), "--silos", *args.silos, "--cycle", args.cycle]
    if dry:
        cmd.append("--dry-run")
    # if walker supports --live only when not dry; ignore

    log_path = LOG_DIR / "daily_vaultwalker.log"
    started = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            f"\n=== vaultwalker_cron {started} dry={dry} silos={args.silos} "
            f"cycle={args.cycle} timeout={args.timeout} ===\n"
        )

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
        rc = proc.returncode
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc = 124
        out = f"TIMEOUT after {args.timeout}s\n{(e.stdout or '')}\n{(e.stderr or '')}"
    except Exception as e:
        rc = 1
        out = f"LAUNCH_ERROR {type(e).__name__}: {e}"

    with log_path.open("a", encoding="utf-8") as log:
        log.write(out[-50000:])
        log.write(f"\n=== exit {rc} ===\n")

    parsed = parse_summary_from_stdout(out)
    # vaultwalker may nest summary
    if isinstance(parsed.get("summary"), dict):
        silo_stats = parsed["summary"]
    else:
        silo_stats = {k: v for k, v in parsed.items() if k not in ("status", "meta", "feedback")}

    feedback = evaluate_feedback(silo_stats if isinstance(silo_stats, dict) else {}, dry, list(args.silos), rc)
    payload = {
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry,
        "silos": list(args.silos),
        "exit_code": rc,
        "walker_status": parsed.get("status"),
        "silo_stats": silo_stats,
        "feedback": feedback,
        "version": "vaultwalker_cron/1.0",
    }

    FEEDBACK_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with FEEDBACK_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    try:
        FEEDBACK_MD.parent.mkdir(parents=True, exist_ok=True)
        FEEDBACK_MD.write_text(render_md(payload), encoding="utf-8")
    except Exception as e:
        print(f"md write fail: {e}")

    # Cron-visible one-liner (non-empty so no_agent delivers when useful)
    print(
        f"VaultWalker score={feedback.get('score')} dry={dry} "
        f"idx={feedback.get('totals', {}).get('indexes')} "
        f"resurface={feedback.get('totals', {}).get('resurfaced')} "
        f"moved={feedback.get('totals', {}).get('moved')} exit={rc}"
    )
    _refresh_indexes()
    return 0 if rc == 0 else rc




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
