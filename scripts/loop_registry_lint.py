#!/usr/bin/env python3
"""N5 — Loop registry lint (meta, always dry-run / report-only).

Inventory cron/jobs.json + known STOP/lock paths + known loop scripts.
Diff against Codifying-Loops-Guardrails-Map expected surfaces.

Out:
  D:/PhronesisVault/Operations/logs/loop-registry-lint-latest.json
  D:/PhronesisVault/Operations/logs/loop-registry-lint-latest.md

Exit 0 always (soft-fail advisory) unless --strict and unknown critical scripts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

HERMES = Path(r"D:\HermesData")
SCRIPTS = HERMES / "scripts"
STATE = HERMES / "state"
CRON_JOBS = HERMES / "cron" / "jobs.json"
OPS_LOG = Path(r"D:\PhronesisVault\Operations\logs")
OUT_JSON = OPS_LOG / "loop-registry-lint-latest.json"
OUT_MD = OPS_LOG / "loop-registry-lint-latest.md"

# Expected loop surfaces from Codifying-Loops-Guardrails-Map §2
EXPECTED_SCRIPTS = {
    "silo_continuous_loop.py": {"plane": "kitchen", "stop": "silo_continuous.STOP", "single_writer": True},
    "silo_orchestrator_tick.py": {"plane": "kitchen", "stop": "silo_continuous.STOP", "single_writer": True},
    "silo_recovery_single_writer.py": {"plane": "kitchen", "stop": None, "single_writer": True},
    "silo_self_heal_monitor.py": {"plane": "kitchen", "stop": None, "single_writer": False},
    "model_mgmt_light_cron.py": {"plane": "model", "stop": None, "single_writer": True},
    "model_mgmt_full_cron.py": {"plane": "model", "stop": None, "single_writer": True},
    "vaultwalker.py": {"plane": "vw", "stop": "vaultwalker_travel.STOP", "single_writer": False},
    "vaultwalker_cron.py": {"plane": "vw", "stop": "vaultwalker_travel.STOP", "single_writer": False},
    "stack_healing_once.py": {"plane": "gateway", "stop": None, "single_writer": False},
    "single_gateway_instance_check.py": {"plane": "gateway", "stop": None, "single_writer": False},
    "skill_evo_loop.py": {"plane": "meta", "stop": None, "single_writer": False},
    "loop-lint-gate.py": {"plane": "meta", "stop": None, "single_writer": False},
    "detective_codify_smoke.py": {"plane": "codify", "stop": None, "single_writer": False},
    "self_correcting_codify_loop.py": {"plane": "codify", "stop": None, "single_writer": False},
    "canon_conflict_lint.py": {"plane": "codify", "stop": None, "single_writer": False},
    "loop_registry_lint.py": {"plane": "meta", "stop": None, "single_writer": False},
    "prepare_grok_escalation_brief.py": {"plane": "judgment", "stop": None, "single_writer": False},
    "entity_mine.py": {"plane": "codify", "stop": None, "single_writer": False},
    # kitchen scoreboard (Sovereign Ops Pulse v1+) — no_agent 30m rollup
    "sovereign_ops_pulse.py": {"plane": "kitchen", "stop": None, "single_writer": False},
    # shared atomic publish SSOT (v1.7+)
    "atomic_io.py": {"plane": "kitchen", "stop": None, "single_writer": False},
}

STOP_LOCK_PATHS = [
    STATE / "silo_continuous.STOP",
    STATE / "silo_autonomous.STOP",
    STATE / "silo_continuous.lock",
    STATE / "silo_continuous.pid",
    STATE / "intent_queue.STOP",
    STATE / "vaultwalker_travel.STOP",
]

KNOWN_RECEIPTS = [
    OPS_LOG / "silo-self-heal-post-verify-latest.json",
    OPS_LOG / "detective-codify-smoke-latest.json",
    OPS_LOG / "silo-recovery-single-writer-latest.md",
    OPS_LOG / "canon-conflict-latest.json",
    OPS_LOG / "loop-registry-lint-latest.json",
    OPS_LOG / "sovereign-ops-pulse-latest.json",
    OPS_LOG / "citadel-channel-audit-latest.json",
    OPS_LOG / "obsidian-five-item-closed-cook-latest.json",
    OPS_LOG / "domain-tag-batch-latest.json",
    HERMES / "logs" / "wave2-link-clarity-cook-latest.json",
    HERMES / "logs" / "wikilink-false-positive-audit-latest.json",
    HERMES / "logs" / "five-item-clarity-cook-latest.json",
    HERMES / "logs" / "stack-reconcile-latest.json",
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jobs() -> list[dict]:
    if not CRON_JOBS.is_file():
        return []
    data = json.loads(CRON_JOBS.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    if isinstance(jobs, dict):
        return list(jobs.values())
    return list(jobs)


def script_from_job(j: dict) -> str | None:
    for k in ("script", "command", "cmd"):
        v = j.get(k)
        if isinstance(v, str) and v.strip():
            name = Path(v.replace("\\", "/")).name
            if name.endswith(".py"):
                return name
            # embedded path
            for part in v.replace("\\", "/").split():
                if part.endswith(".py"):
                    return Path(part).name
    prompt = j.get("prompt") or ""
    for token in str(prompt).replace("\\", "/").split():
        if token.endswith(".py"):
            return Path(token).name
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    issues: list[dict] = []
    jobs = load_jobs()
    enabled = [j for j in jobs if j.get("enabled") is True]
    paused = [j for j in jobs if j.get("enabled") is False or j.get("state") == "paused"]

    job_scripts: list[dict] = []
    for j in jobs:
        sn = script_from_job(j)
        row = {
            "id": j.get("id"),
            "name": j.get("name"),
            "enabled": bool(j.get("enabled")),
            "state": j.get("state"),
            "no_agent": bool(j.get("no_agent")),
            "schedule": (j.get("schedule_display") or j.get("schedule") or ""),
            "script": sn,
            "deliver": j.get("deliver"),
        }
        job_scripts.append(row)
        if sn and sn not in EXPECTED_SCRIPTS and j.get("enabled"):
            issues.append(
                {
                    "class": "unknown_enabled_script",
                    "detail": f"enabled cron script not in map: {sn}",
                    "job": j.get("name"),
                }
            )

    missing_scripts = []
    present_scripts = []
    for name, meta in EXPECTED_SCRIPTS.items():
        p = SCRIPTS / name
        if p.is_file():
            present_scripts.append(name)
        else:
            missing_scripts.append(name)
            issues.append({"class": "missing_script", "detail": name, "job": None})

    stop_state = []
    for p in STOP_LOCK_PATHS:
        stop_state.append({"path": str(p), "exists": p.is_file()})

    receipt_state = []
    for p in KNOWN_RECEIPTS:
        receipt_state.append({"path": str(p.name), "exists": p.is_file()})
        if not p.is_file() and p.name in {
            "silo-self-heal-post-verify-latest.json",
            "detective-codify-smoke-latest.json",
        }:
            issues.append({"class": "missing_receipt", "detail": p.name, "job": None})

    # dual continuous risk: script exists but no recovery companion
    if (SCRIPTS / "silo_continuous_loop.py").is_file() and not (
        SCRIPTS / "silo_recovery_single_writer.py"
    ).is_file():
        issues.append(
            {
                "class": "dual_script",
                "detail": "continuous without single-writer recovery script",
                "job": None,
            }
        )

    report = {
        "at": utc(),
        "ok": len([i for i in issues if i["class"] in {"dual_script", "missing_script"}]) == 0,
        "n_jobs": len(jobs),
        "n_enabled": len(enabled),
        "n_paused": len(paused),
        "n_expected_scripts": len(EXPECTED_SCRIPTS),
        "n_present_scripts": len(present_scripts),
        "missing_scripts": missing_scripts,
        "jobs": job_scripts,
        "stop_lock_paths": stop_state,
        "receipts": receipt_state,
        "issues": issues,
        "canon": [
            "Operations/Codifying-Loops-Guardrails-Map-2026-07-18",
            "Operations/Self-Correcting-Codify-Loops-Safe-Surfaces-CANONICAL-2026-07-18",
        ],
    }

    OPS_LOG.mkdir(parents=True, exist_ok=True)
    if atomic_write_json is not None:
        atomic_write_json(OUT_JSON, report, min_bytes=20)
    else:
        OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Loop registry lint — {report['at']}",
        "",
        f"- jobs: **{len(jobs)}** (enabled **{len(enabled)}**, paused/disabled **{len(paused)}**)",
        f"- expected scripts present: **{len(present_scripts)}/{len(EXPECTED_SCRIPTS)}**",
        f"- issues: **{len(issues)}**",
        f"- ok: **{report['ok']}**",
        "",
        "## Missing scripts",
        "",
    ]
    if not missing_scripts:
        lines.append("_None_")
    else:
        for m in missing_scripts:
            lines.append(f"- `{m}`")
    lines += ["", "## Issues", ""]
    if not issues:
        lines.append("_None_")
    else:
        for i in issues:
            lines.append(f"- `{i['class']}` — {i['detail']}" + (f" (job={i['job']})" if i.get("job") else ""))
    lines += [
        "",
        "## STOP / lock presence",
        "",
        "| Path | Exists |",
        "|------|:------:|",
    ]
    for s in stop_state:
        lines.append(f"| `{Path(s['path']).name}` | {s['exists']} |")
    lines += [
        "",
        "Report-only. No process kills. No cron mutations.",
        "[[Operations/Codifying-Loops-Guardrails-Map-2026-07-18]]",
        "",
    ]
    md = "\n".join(lines)
    if atomic_write_text is not None:
        atomic_write_text(OUT_MD, md, min_bytes=20)
    else:
        OUT_MD.write_text(md if md.endswith("\n") else md + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"LOOP_REGISTRY ok={report['ok']} jobs={len(jobs)} enabled={len(enabled)} "
            f"issues={len(issues)} missing_scripts={len(missing_scripts)} log={OUT_JSON}"
        )
    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
