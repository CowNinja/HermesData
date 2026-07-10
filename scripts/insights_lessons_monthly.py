#!/usr/bin/env python3
"""Monthly Hermes insights → lessons learned note (thin orchestrator feedback).

Runs `hermes insights` (or uses last cache), extracts top tools/models/platforms,
writes Operations/logs/insights-lessons-YYYY-MM.md + latest pointer.

Proposal-only adjustments listed for Jeff/Hermes to implement later.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
OUT_DIR = VAULT / "Operations" / "logs"
LATEST = OUT_DIR / "insights-lessons-latest.md"
RAW = HERMES / "logs" / "hermes-insights-last.txt"


def run_insights() -> str:
    try:
        proc = subprocess.run(
            ["hermes", "insights"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=str(HERMES),
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception as e:
        text = f"insights_error: {e}\n"
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(text, encoding="utf-8")
    return text


def extract_lessons(text: str) -> dict:
    lessons = []
    # crude heuristics on known report shape
    if "terminal" in text.lower() and re.search(r"terminal\s+\d+", text, re.I):
        lessons.append({
            "signal": "terminal dominates tool calls",
            "lesson": "Push status/scans to script-only crons + grunt_local; keep Grok for judgment.",
            "action": "Prefer vaultwalker_cron / gardener_phase_b / dawn_pulse_script over multi-turn shell.",
        })
    if "cron" in text.lower() and "Sessions" in text:
        lessons.append({
            "signal": "cron is a major session source",
            "lesson": "Agent crons burn tokens; convert health/gallery/housekeeping to no_agent scripts.",
            "action": "Audit jobs.json: no_agent=true for non-judgment jobs.",
        })
    if "discord" in text.lower():
        lessons.append({
            "signal": "Discord traffic is high-token",
            "lesson": "Ultra-brief replies + tool budget ≤3 rounds; deep work in vault MD.",
            "action": "grok-efficiency-mode skill on Discord sessions.",
        })
    if "grok-build" in text.lower() or "phronesis-sovereign" in text.lower():
        lessons.append({
            "signal": "mixed model usage across sessions",
            "lesson": "Hybrid is working: cheap/local for bulk, Grok for driver chat.",
            "action": "Keep primary grok-4.5; delegation/aux on :8091.",
        })
    if not lessons:
        lessons.append({
            "signal": "insights captured",
            "lesson": "Review raw report for token outliers.",
            "action": "Read hermes-insights-last.txt and set one cut next month.",
        })
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "lessons": lessons,
        "raw_bytes": len(text),
        "raw_path": str(RAW),
    }


def render(payload: dict, text_head: str) -> str:
    ym = datetime.now().strftime("%Y-%m")
    lines = [
        f"# Hermes Insights Lessons — {ym}",
        "",
        f"**Generated:** {payload['ts']}",
        f"**Raw:** `{payload['raw_path']}` ({payload['raw_bytes']} bytes)",
        "",
        "Purpose: train the Machine (thin orchestrator) from real usage — not silo content.",
        "Vision: [[Operations/Autonomy-Pathway-Dreamer-Worker-2026-07-10]]",
        "",
        "## Lessons",
        "",
    ]
    for i, L in enumerate(payload["lessons"], 1):
        lines.append(f"### {i}. {L['signal']}")
        lines.append(f"- **Lesson:** {L['lesson']}")
        lines.append(f"- **Action:** {L['action']}")
        lines.append("")
    lines += [
        "## Next month gate",
        "- Did tool/token mix move toward scripts + local grunt?",
        "- Any new skill worth creating from repeated pain?",
        "",
        "## Raw head (truncated)",
        "```",
        text_head[:2500],
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text = run_insights()
    payload = extract_lessons(text)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ym = datetime.now().strftime("%Y-%m")
    dated = OUT_DIR / f"insights-lessons-{ym}.md"
    body = render(payload, text)
    dated.write_text(body, encoding="utf-8")
    LATEST.write_text(body, encoding="utf-8")
    (HERMES / "logs" / "insights-lessons-latest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(f"insights lessons -> {dated} lessons={len(payload['lessons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
