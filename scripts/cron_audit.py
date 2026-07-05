#!/usr/bin/env python3
"""
cron_audit.py -- Read-only Hermes cron fleet auditor (Phase 0 curator).

Scans cron/jobs.json, classifies load/failures, writes JSON report.
Does NOT auto-disable jobs -- use recommendations + operator gate.

Usage:
  python cron_audit.py
  python cron_audit.py --stdout
  python cron_audit.py --summary
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERMES_ROOT = Path(r"D:\HermesData")
JOBS_PATH = HERMES_ROOT / "cron" / "jobs.json"
REPORT_PATH = Path(r"D:\PhronesisVault\Operations\logs\cron-audit-report.json")

FAILURE_HINTS: Dict[str, str] = {
    "Fieldy script not found": "Pause fieldy-hourly-pull until Fieldy-RecentPull.ps1 exists, or fix path.",
    "Response remained truncated": "Switch to no_agent script or reduce prompt; LLM delivery truncation.",
    "dirty files": "Self-Recovery-Watchdog: dirty working tree is normal on dev -- should not exit 1.",
    "daily_model_audit": "Use venv python + extend timeout; or merge into model_management_agent --full-tick.",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jobs() -> List[Dict[str, Any]]:
    if not JOBS_PATH.is_file():
        return []
    return json.loads(JOBS_PATH.read_text(encoding="utf-8-sig")).get("jobs") or []


def _freq_score(schedule: Dict[str, Any]) -> int:
    if not schedule:
        return 1
    kind = schedule.get("kind")
    if kind == "interval":
        mins = int(schedule.get("minutes") or 60)
        if mins <= 5:
            return 12
        if mins <= 15:
            return 8
        if mins <= 60:
            return 4
        return 2
    expr = str(schedule.get("expr") or "")
    if "*/5" in expr:
        return 12
    if "*/15" in expr or "*/10" in expr:
        return 8
    if "*/30" in expr or "0 *" in expr:
        return 4
    if "0 */6" in expr:
        return 3
    if "0 0" in expr or "0 3" in expr or "0 9" in expr:
        return 1
    return 2


def _hint_for_error(err: str) -> str:
    err_l = (err or "").lower()
    for key, hint in FAILURE_HINTS.items():
        if key.lower() in err_l:
            return hint
    return "Inspect last_error; consider pause, no_agent script, or merge into existing tick."


def build_report() -> Dict[str, Any]:
    jobs = _load_jobs()
    enabled = [j for j in jobs if j.get("enabled")]
    failed = [
        j for j in jobs
        if j.get("enabled") and (j.get("last_status") == "error" or j.get("last_error"))
    ]

    rows: List[Dict[str, Any]] = []
    for j in jobs:
        sched = j.get("schedule") or {}
        llm = not j.get("no_agent") and not j.get("script")
        load = _freq_score(sched) * (5 if llm else 1)
        rows.append(
            {
                "id": j.get("id"),
                "name": j.get("name"),
                "enabled": bool(j.get("enabled")),
                "no_agent": bool(j.get("no_agent")),
                "llm_agent": llm,
                "schedule": sched.get("display") or sched.get("expr") or sched.get("kind"),
                "load_score": load,
                "last_status": j.get("last_status"),
                "last_error_preview": (j.get("last_error") or "")[:200] or None,
                "fix_hint": _hint_for_error(j.get("last_error") or "") if j.get("last_error") else None,
            }
        )

    rows.sort(key=lambda r: r["load_score"], reverse=True)
    high_load = [r for r in rows if r["enabled"] and r["load_score"] >= 8]

    recommendations: List[str] = []
    if len(failed) >= 3:
        recommendations.append(
            f"Pause or fix {len(failed)} failing jobs -- Discord noise + wasted gateway cycles."
        )
    if sum(1 for r in rows if r["enabled"] and r["llm_agent"]) > 5:
        recommendations.append(
            "Consolidate LLM crons into fewer thin-orchestrator + script-leaf patterns (vault AGENTS.md)."
        )
    if len(high_load) >= 2:
        recommendations.append(
            f"Review {len(high_load)} high-frequency jobs -- prefer no_agent scripts (stack health pattern)."
        )
    recommendations.append(
        "Phase 1: cron_curator_agent.py -- bounded tick like model_management_agent (max 4 fixes/tick)."
    )

    return {
        "timestamp": _utc_now(),
        "total": len(jobs),
        "enabled": len(enabled),
        "failed_count": len(failed),
        "status_counts": dict(Counter(j.get("last_status") or "unknown" for j in jobs)),
        "no_agent_enabled": sum(1 for j in enabled if j.get("no_agent")),
        "llm_agent_enabled": sum(1 for j in enabled if not j.get("no_agent")),
        "high_load_jobs": high_load[:8],
        "failures": [
            {
                "name": j.get("name"),
                "id": j.get("id"),
                "error": (j.get("last_error") or "")[:300],
                "hint": _hint_for_error(j.get("last_error") or ""),
            }
            for j in failed
        ],
        "recommendations": recommendations,
        "jobs": rows,
        "phase": "audit_v0",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes cron fleet auditor")
    parser.add_argument("--stdout", action="store_true", help="Print full JSON only")
    parser.add_argument("--summary", action="store_true", help="Compact summary JSON")
    args = parser.parse_args()

    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.summary:
        slim = {k: report[k] for k in (
            "timestamp", "total", "enabled", "failed_count", "status_counts",
            "no_agent_enabled", "llm_agent_enabled", "recommendations", "failures",
        )}
        print(json.dumps(slim, indent=2))
    elif args.stdout:
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())