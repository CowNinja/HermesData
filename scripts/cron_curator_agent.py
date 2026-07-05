#!/usr/bin/env python3
"""
cron_curator_agent.py -- Bounded Hermes cron fleet curator (Phase 1 + 2).

Phase 1: audit, probe script jobs, pause missing deps, clear stale errors.
Phase 2: cron_registry.yaml SSOT + sovereign-router LLM diagnose on full-tick
(when stack green). Whitelisted fixes only; no job create/delete.

Usage:
  python cron_curator_agent.py --tick
  python cron_curator_agent.py --full-tick    # + probes + LLM diagnose
  python cron_curator_agent.py --summary
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

HERMES_ROOT = Path(r"D:\HermesData")
VAULT = Path(r"D:\PhronesisVault")
JOBS_PATH = HERMES_ROOT / "cron" / "jobs.json"
STATE_OUT = VAULT / "Operations" / "cron-curator-state.json"
LOG_PATH = VAULT / "Operations" / "logs" / "cron-curator-agent.jsonl"
AUDIT_SCRIPT = HERMES_ROOT / "scripts" / "cron_audit.py"
REGISTRY_PATH = HERMES_ROOT / "config" / "cron_registry.yaml"
VAULT_AGENTS = VAULT / "AGENTS.md"
VENV_PY = HERMES_ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
PROXY_CHAT = "http://127.0.0.1:8091/v1/chat/completions"

MAX_ACTIONS_PER_TICK = 4
CONSECUTIVE_FAIL_PAUSE = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: Dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")


def _load_jobs() -> List[Dict[str, Any]]:
    if not JOBS_PATH.is_file():
        return []
    return json.loads(JOBS_PATH.read_text(encoding="utf-8-sig")).get("jobs") or []


def _save_jobs(jobs: List[Dict[str, Any]]) -> None:
    JOBS_PATH.write_text(
        json.dumps({"jobs": jobs}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_registry() -> Dict[str, Any]:
    if not REGISTRY_PATH.is_file() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _stack_green() -> bool:
    for port in (8090, 8091):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                pass
        except OSError:
            return False
    return True


def _master_plan_excerpt(max_chars: int = 1200) -> str:
    if not VAULT_AGENTS.is_file():
        return "Prefer no_agent script leaves. Thin L3 orchestrator."
    text = VAULT_AGENTS.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]


def _llm_diagnose_job(job: Dict[str, Any], issue: Dict[str, Any], registry: Dict[str, Any]) -> Dict[str, Any]:
    """Ask local sovereign router for bounded cron fix recommendation (JSON only)."""
    llm_cfg = registry.get("llm_diagnose") or {}
    if not llm_cfg.get("enabled", True):
        return {"skipped": True, "reason": "llm_diagnose_disabled"}
    if llm_cfg.get("only_when_stack_green", True) and not _stack_green():
        return {"skipped": True, "reason": "stack_not_green"}
    model = str(llm_cfg.get("model") or "phronesis-sovereign-classify")
    timeout = int(llm_cfg.get("timeout_sec") or 45)
    principles = (registry.get("master_plan") or {}).get("principles") or []
    prompt = (
        "You are the Hermes cron curator. Return ONLY valid JSON with keys: "
        "fix (one of pause_job|clear_stale_error|recommend_no_agent|set_model_sovereign_auto|none), "
        "reason (string), script_suggestion (string or null).\n"
        f"Master plan principles: {principles}\n"
        f"Job name: {job.get('name')}\n"
        f"enabled: {job.get('enabled')} no_agent: {job.get('no_agent')} script: {job.get('script')}\n"
        f"schedule: {job.get('schedule_display') or job.get('schedule')}\n"
        f"model: {job.get('model')} provider: {job.get('provider')}\n"
        f"last_error excerpt: {(job.get('last_error') or issue.get('message') or '')[:400]}\n"
        "Pick the safest fix aligned with no_agent script leaves when truncation or LLM load is the issue."
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.1,
    }
    try:
        req = urllib.request.Request(
            PROXY_CHAT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = str((body.get("choices") or [{}])[0].get("message", {}).get("content", "")).strip()
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {"ok": False, "error": "no_json", "raw": text[:200]}
        parsed = json.loads(m.group(0))
        fix = str(parsed.get("fix") or "none")
        allowed = set(registry.get("whitelisted_fixes") or []) | {"none"}
        if fix not in allowed:
            parsed["fix"] = "none"
            parsed["rejected_fix"] = fix
        return {"ok": True, "recommendation": parsed, "model": model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def llm_remediate(
    issues: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
    registry: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Apply whitelisted fixes from sovereign-router LLM diagnose (bounded)."""
    llm_cfg = registry.get("llm_diagnose") or {}
    max_jobs = int(llm_cfg.get("max_jobs_per_tick") or 2)
    actions: List[Dict[str, Any]] = []
    changed = False
    for issue in issues:
        if len(actions) >= MAX_ACTIONS_PER_TICK or len(actions) >= max_jobs:
            break
        if issue.get("fix") not in ("probe", "recommend"):
            continue
        jid = issue.get("job_id")
        job = next((j for j in jobs if j.get("id") == jid), None)
        if not job or not job.get("enabled"):
            continue
        diag = _llm_diagnose_job(job, issue, registry)
        if not diag.get("ok"):
            actions.append({"action": "llm_diagnose", "job_id": jid, **diag})
            continue
        rec = diag.get("recommendation") or {}
        fix = str(rec.get("fix") or "none")
        action: Dict[str, Any] = {
            "action": "llm_diagnose",
            "job_id": jid,
            "job_name": job.get("name"),
            "fix": fix,
            "reason": rec.get("reason"),
            "script_suggestion": rec.get("script_suggestion"),
        }
        if fix == "none" or dry_run:
            action["dry_run"] = dry_run
            actions.append(action)
            continue
        if fix == "pause_job":
            job["enabled"] = False
            job["state"] = "paused"
            job["paused_at"] = _utc_now()
            job["paused_reason"] = f"cron_curator_llm: {rec.get('reason') or 'llm pause'}"
            job["last_error"] = None
            job["last_status"] = "paused"
            changed = True
        elif fix == "clear_stale_error":
            job["last_error"] = None
            job["last_status"] = "ok"
            job["cleared_by_cron_curator_at"] = _utc_now()
            changed = True
        elif fix == "set_model_sovereign_auto":
            job["model"] = "phronesis-sovereign-auto"
            job["provider"] = "phronesis-sovereign"
            changed = True
        elif fix == "recommend_no_agent":
            action["operator_note"] = (
                f"Convert to no_agent script leaf: {rec.get('script_suggestion') or 'see vault AGENTS.md'}"
            )
        actions.append(action)
    if changed and not dry_run:
        _save_jobs(jobs)
    return actions


def _run_audit() -> Dict[str, Any]:
    py = str(VENV_PY) if VENV_PY.is_file() else sys.executable
    try:
        proc = subprocess.run(
            [py, str(AUDIT_SCRIPT), "--summary"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=str(HERMES_ROOT),
        )
        if proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except Exception as exc:
        return {"error": str(exc)}
    return {}


def _probe_script_job(job: Dict[str, Any]) -> Dict[str, Any]:
    script = job.get("script")
    if not script:
        return {"skipped": True, "reason": "no_script"}
    path = HERMES_ROOT / "scripts" / str(script)
    if not path.is_file():
        return {"ok": False, "error": "script_missing", "path": str(path)}
    py = str(VENV_PY) if VENV_PY.is_file() else sys.executable
    try:
        proc = subprocess.run(
            [py, str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=str(job.get("workdir") or HERMES_ROOT),
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-400:],
            "stderr_tail": (proc.stderr or "")[-400:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def assess(*, full: bool = False) -> Dict[str, Any]:
    jobs = _load_jobs()
    audit = _run_audit()
    issues: List[Dict[str, Any]] = []

    for j in jobs:
        if not j.get("enabled"):
            continue
        if j.get("last_status") == "error" or j.get("last_error"):
            issues.append(
                {
                    "code": "C01",
                    "severity": "medium",
                    "job_id": j.get("id"),
                    "job_name": j.get("name"),
                    "message": (j.get("last_error") or "last_status=error")[:200],
                    "fix": "pause" if "not found" in str(j.get("last_error") or "").lower() else "probe",
                }
            )
        llm = not j.get("no_agent") and not j.get("script")
        sched = j.get("schedule") or {}
        if llm and sched.get("kind") == "interval" and int(sched.get("minutes") or 999) <= 15:
            issues.append(
                {
                    "code": "C02",
                    "severity": "low",
                    "job_id": j.get("id"),
                    "job_name": j.get("name"),
                    "message": "High-frequency LLM cron -- consider no_agent script",
                    "fix": "recommend",
                }
            )

    probes: Dict[str, Any] = {}
    if full:
        for issue in [i for i in issues if i.get("fix") == "probe"][:3]:
            job = next((j for j in jobs if j.get("id") == issue.get("job_id")), None)
            if job and job.get("script"):
                probes[issue["job_id"]] = _probe_script_job(job)

    return {
        "audit": audit,
        "issues": issues,
        "probes": probes,
        "job_count": len(jobs),
        "enabled_count": sum(1 for j in jobs if j.get("enabled")),
    }


def remediate(issues: List[Dict[str, Any]], jobs: List[Dict[str, Any]], *, dry_run: bool = False) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for issue in issues:
        if len(actions) >= MAX_ACTIONS_PER_TICK:
            break
        if issue.get("fix") != "pause":
            continue
        err = str(issue.get("message") or "").lower()
        if "not found" not in err and "critical" not in err:
            continue
        jid = issue.get("job_id")
        job = next((j for j in jobs if j.get("id") == jid), None)
        if not job or not job.get("enabled"):
            continue
        action = {
            "action": "pause_job",
            "job_id": jid,
            "job_name": job.get("name"),
            "reason": "cron_curator: missing dependency",
        }
        if dry_run:
            action["dry_run"] = True
            actions.append(action)
            continue
        job["enabled"] = False
        job["state"] = "paused"
        job["paused_at"] = _utc_now()
        job["paused_reason"] = action["reason"]
        job["last_error"] = None
        job["last_status"] = "paused"
        actions.append(action)
    if actions and not dry_run and any(a.get("action") == "pause_job" for a in actions):
        _save_jobs(jobs)
    return actions


def clear_stale_errors(
    jobs: List[Dict[str, Any]],
    probes: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Clear last_error when --full-tick probe proves script now healthy."""
    actions: List[Dict[str, Any]] = []
    changed = False
    for jid, probe in probes.items():
        if not probe.get("ok"):
            continue
        job = next((j for j in jobs if j.get("id") == jid), None)
        if not job or not (job.get("last_error") or job.get("last_status") == "error"):
            continue
        action = {
            "action": "clear_stale_error",
            "job_id": jid,
            "job_name": job.get("name"),
        }
        if dry_run:
            action["dry_run"] = True
            actions.append(action)
            continue
        job["last_error"] = None
        job["last_status"] = "ok"
        job["cleared_by_cron_curator_at"] = _utc_now()
        actions.append(action)
        changed = True
    if changed and not dry_run:
        _save_jobs(jobs)
    return actions


def run_tick(*, mode: str = "tick", dry_run: bool = False) -> Dict[str, Any]:
    assessment = assess(full=(mode == "full"))
    jobs = _load_jobs()
    remediations = remediate(assessment.get("issues") or [], jobs, dry_run=dry_run)
    registry = _load_registry()
    if mode == "full":
        remediations.extend(
            clear_stale_errors(jobs, assessment.get("probes") or {}, dry_run=dry_run)
        )
        remaining = [
            i
            for i in (assessment.get("issues") or [])
            if i.get("job_id") not in {r.get("job_id") for r in remediations if r.get("job_id")}
        ]
        if remaining and registry:
            remediations.extend(
                llm_remediate(remaining, jobs, registry, dry_run=dry_run)
            )
    failed = int((assessment.get("audit") or {}).get("failed_count") or 0)
    status = "green"
    if failed >= 3:
        status = "amber"
    if failed >= 8:
        status = "red"

    state = {
        "agent": "cron_curator_agent",
        "version": "1.1",
        "registry_path": str(REGISTRY_PATH),
        "mode": mode,
        "updated_at": _utc_now(),
        "status": status,
        "failed_count": failed,
        "issue_count": len(assessment.get("issues") or []),
        "remediation_count": len(remediations),
        "assessment": assessment,
        "remediations": remediations,
        "capabilities": [
            "Audit cron/jobs.json via cron_audit.py",
            "Flag failing + high-frequency LLM crons",
            "Probe script jobs on --full-tick",
            "Auto-pause jobs with missing script dependencies (bounded)",
            "Clear stale last_error when full-tick probe passes",
            "Phase 2: cron_registry.yaml + sovereign-router LLM diagnose (full-tick)",
            "Writes cron-curator-state.json for dashboard consumers",
        ],
        "limitations": [
            "Will NOT create or delete cron jobs",
            "Will NOT enable paused jobs without operator",
            "Will NOT run LLM agent crons during probe",
            "LLM diagnose only applies whitelisted fixes from cron_registry.yaml",
            f"Max {MAX_ACTIONS_PER_TICK} remediations per tick",
        ],
        "operator_commands": {
            "tick": f'"{VENV_PY}" D:\\HermesData\\scripts\\cron_curator_agent.py --tick --summary',
            "full_tick": f'"{VENV_PY}" D:\\HermesData\\scripts\\cron_curator_agent.py --full-tick --summary',
            "audit": f'"{VENV_PY}" D:\\HermesData\\scripts\\cron_audit.py --summary',
        },
    }
    if not dry_run:
        STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
        STATE_OUT.write_text(json.dumps(state, indent=2), encoding="utf-8")
    _log({"event": "tick", "mode": mode, "status": status, "failed": failed})
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded Hermes cron curator")
    parser.add_argument("--tick", action="store_true")
    parser.add_argument("--full-tick", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    mode = "full" if args.full_tick else "tick"
    state = run_tick(mode=mode, dry_run=args.dry_run)
    if args.summary:
        slim = {k: state[k] for k in (
            "status", "failed_count", "issue_count", "remediation_count", "mode", "updated_at",
        ) if k in state}
        print(json.dumps(slim, indent=2))
    else:
        print(json.dumps(state, indent=2))
    return 0 if state.get("status") != "red" else 1


if __name__ == "__main__":
    raise SystemExit(main())