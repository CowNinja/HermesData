#!/usr/bin/env python3
"""Driver/Judgment plane one-shot pulse (read-only composite).

Research (2026-07-20):
  - Google SRE readiness: one composite check; alert on red only
  - Anthropic Effective Agents: programmatic gates; supervisor doesn't thrash
  - Silent-green pattern (this stack): GREEN quiet; YELLOW/RED receipts
  - Codifying-Loops map: measure before monologue RCA

Runs (fixed argv only ? never free-form shell):
  1. stack_snapshot.py
  2. local_offline_mode_check.py --no-smoke
  3. loop_registry_lint.py
  4. canon_conflict_lint.py
  5. judgment_backlog.py --list  (informational)
  6. stack_single_instance_audit.py  (measure-only; never kill/start)

Writes:
  D:/PhronesisVault/Operations/logs/driver-judgment-pulse-latest.json
  D:/PhronesisVault/Operations/logs/driver-judgment-pulse-latest.md

Exit:
  0 = GREEN or YELLOW (job ran; yellow = advisory)
  1 = RED (real fail ? surface to Jeff/Driver)
  2 = misconfig / runner error

Usage:
  python D:/HermesData/scripts/driver_judgment_pulse.py
  python D:/HermesData/scripts/driver_judgment_pulse.py --json
  python D:/HermesData/scripts/driver_judgment_pulse.py --strict  # yellow?exit 1

Canon: Operations/Grok-Thread-Architecture-Judgment-CANONICAL-2026-07-18 ?8
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from atomic_io import atomic_write_json, atomic_write_text
except ImportError:  # pragma: no cover
    atomic_write_json = None  # type: ignore
    atomic_write_text = None  # type: ignore

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
PY = sys.executable
VAULT = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT_JSON = VAULT / "driver-judgment-pulse-latest.json"
RECEIPT_MD = VAULT / "driver-judgment-pulse-latest.md"
THREAD = "1524846849360531456"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_check(name: str, argv: List[str], timeout: int = 120) -> Dict[str, Any]:
    cmd = [PY, str(SCRIPTS / argv[0]), *argv[1:]]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        out = (r.stdout or "")[-800:]
        err = (r.stderr or "")[-400:]
        return {
            "name": name,
            "rc": int(r.returncode),
            "ok": r.returncode == 0,
            "stdout_tail": out,
            "stderr_tail": err,
            "cmd": " ".join(argv),
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "rc": 124,
            "ok": False,
            "stdout_tail": "",
            "stderr_tail": f"timeout after {timeout}s",
            "cmd": " ".join(argv),
        }
    except Exception as e:
        return {
            "name": name,
            "rc": 2,
            "ok": False,
            "stdout_tail": "",
            "stderr_tail": f"{type(e).__name__}:{e}",
            "cmd": " ".join(argv),
        }


def load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def image_tenant_context() -> Dict[str, Any]:
    """Soft context: 8090_down while image lock held is expected (12GB law)."""
    lock_path = Path(r"D:\HermesData\state\image_jobs\gpu_tenant.lock")
    meta_path = Path(r"D:\HermesData\state\image_jobs\gpu_tenant.json")
    held = False
    detail = "no_lock"
    if lock_path.is_file():
        try:
            raw = lock_path.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                held = True
                detail = f"plain:{raw[:60]}"
        except Exception as exc:
            held = True
            detail = f"lock_err:{exc}"[:60]
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("owner") or meta.get("pid"):
                held = True
                detail = f"json:{meta.get('owner') or meta.get('job')}"
        except Exception:
            pass
    return {"held": held, "detail": detail}


def classify(checks: Dict[str, Dict[str, Any]]) -> Tuple[str, str, List[str]]:
    """Return color, summary, red_reasons."""
    reds: List[str] = []
    yellows: List[str] = []

    snap = checks.get("stack_snapshot") or {}
    offline = checks.get("local_offline") or {}
    loops = checks.get("loop_registry") or {}
    canons = checks.get("canon_conflict") or {}
    img = image_tenant_context()

    # stack snapshot ? rc!=0 is yellow unless we can prove ports down via receipt
    snap_rec = load_json(VAULT / "stack-snapshot-latest.json")
    green = (snap_rec.get("green") or {}) if isinstance(snap_rec, dict) else {}
    color_hint = (green.get("color") or "").upper()
    if not snap.get("ok"):
        if color_hint == "RED":
            reds.append("stack_snapshot RED")
        else:
            yellows.append(f"stack_snapshot rc={snap.get('rc')}")
    elif color_hint == "RED":
        reds.append("stack_snapshot receipt RED")
    elif color_hint == "YELLOW":
        yellows.append("stack_snapshot YELLOW")

    # offline ? exact status match (avoid 'READY' substring hitting NOT_READY)
    off_rec = load_json(VAULT / "local-offline-mode-latest.json")
    status = str(off_rec.get("status") or "").strip().upper()
    ready_flag = bool(off_rec.get("ready_local_first") or off_rec.get("ready"))
    off_issues = off_rec.get("issues") or []
    if isinstance(off_issues, str):
        off_issues = [off_issues]
    bleed_n = int(off_rec.get("aux_grok_bleed_count") or 0)
    if status in ("READY_LOCAL_FIRST", "READY") or ready_flag:
        pass  # plane OK
    elif status == "NOT_READY" or off_issues or not offline.get("ok"):
        if off_rec.get("hard_fail") or off_rec.get("color") == "RED":
            reds.append("local_offline hard_fail")
        else:
            detail = ",".join(str(x) for x in off_issues) if off_issues else f"rc={offline.get('rc')}"
            # 12GB law + router freeze 2026-07-21: 8090_down under live image lock = expected soft
            issues_l = " ".join(str(x).lower() for x in off_issues)
            if img.get("held") and ("8090" in issues_l or "8090" in detail):
                yellows.append(f"expected_image_tenant:8090_down({img.get('detail')})")
            else:
                yellows.append(f"local_offline:{detail}")
    if bleed_n > 0:
        yellows.append(f"aux_grok_bleed={bleed_n}")

    # loop registry ? issues>0 is yellow (lint is advisory unless --strict elsewhere)
    loop_rec = load_json(VAULT / "loop-registry-lint-latest.json")
    issues = loop_rec.get("issues")
    if isinstance(issues, list) and len(issues) > 0:
        yellows.append(f"loop_registry issues={len(issues)}")
    elif isinstance(issues, int) and issues > 0:
        yellows.append(f"loop_registry issues={issues}")
    elif not loops.get("ok"):
        # script may exit 1 on unknowns; treat as yellow not red
        yellows.append(f"loop_registry rc={loops.get('rc')}")

    # canon conflict ? hard conflicts = red; soft = yellow
    can_rec = load_json(VAULT / "canon-conflict-latest.json")
    hard = can_rec.get("hard") or can_rec.get("hard_count") or can_rec.get("hard_conflicts")
    soft = can_rec.get("soft") or can_rec.get("soft_count") or can_rec.get("soft_conflicts")
    try:
        hard_n = len(hard) if isinstance(hard, list) else int(hard or 0)
    except Exception:
        hard_n = 0
    try:
        soft_n = len(soft) if isinstance(soft, list) else int(soft or 0)
    except Exception:
        soft_n = 0
    if hard_n > 0:
        reds.append(f"canon hard_conflicts={hard_n}")
    elif soft_n > 0:
        yellows.append(f"canon soft_conflicts={soft_n}")
    elif not canons.get("ok"):
        # default exit 1 on conflicts ? if no receipt counts, yellow
        yellows.append(f"canon_conflict rc={canons.get('rc')}")

    # single-stack permanence (2026-07-22 P2) — measure only
    # Admin schtask residual = advisory only; TRUE_DUAL = red; health flaps -> dual
    ss = load_json(Path(r"D:\HermesData\logs\stack_single_instance_audit_latest.json"))
    if not ss:
        ss = load_json(VAULT / "stack-single-instance-audit-latest.json")
    if ss:
        roles = ss.get("roles") or {}
        true_dual = False
        not_single = []
        down = []
        for rname, r in roles.items() if isinstance(roles, dict) else []:
            if not isinstance(r, dict):
                continue
            note = str(r.get("note") or "")
            lis = r.get("listeners") or []
            if "TRUE_DUAL" in note or (isinstance(lis, list) and len(lis) > 1):
                true_dual = True
            if r.get("single_instance") is False:
                not_single.append(rname)
            if r.get("health") is False and rname in ("gateway", "proxy_8091"):
                # gateway/proxy down is real yellow; brain handled by offline check / image lock
                down.append(rname)
        if true_dual:
            reds.append("single_stack TRUE_DUAL_LISTENERS")
        elif not_single:
            yellows.append(f"single_stack not_single:{','.join(not_single)}")
        elif down:
            yellows.append(f"single_stack_core_down:{','.join(down)}")
        # Jeff-Admin residuals (Grok-Hermes-Loop Ready) — do not yellow pulse
    else:
        yellows.append("single_stack_audit_missing")

    # backup health (2026-08-01) — measure only; RED escalates, YELLOW advisory
    bh = load_json(Path(r"D:\HermesData\state\backup_health_last.json"))
    if bh:
        bcolor = str(bh.get("color") or "").upper()
        issues = bh.get("issues") or []
        if bcolor == "RED":
            reds.append(f"backup_health RED: {'; '.join(issues)[:120]}")
        elif bcolor == "YELLOW":
            yellows.append(
                f"backup_health YELLOW: {'; '.join((bh.get('warns') or issues)[:2])[:100]}"
            )
    else:
        yellows.append("backup_health_missing")

    if reds:
        return "RED", "; ".join(reds), reds
    if yellows:
        return "YELLOW", "; ".join(yellows), reds
    return "GREEN", "driver pulse clean: snapshot+offline+loop+canon+single_stack+backup", reds


def backlog_open_count(backlog_check: Dict[str, Any]) -> int:
    tail = backlog_check.get("stdout_tail") or ""
    try:
        # judgment_backlog --list prints JSON with count
        start = tail.find("{")
        if start >= 0:
            data = json.loads(tail[start:])
            rows = data.get("rows") or []
            return sum(1 for r in rows if (r.get("status") or "") not in ("done", "closed", "rejected"))
        if '"count"' in tail:
            data = json.loads(tail[tail.index("{") :])
            return int(data.get("count") or 0)
    except Exception:
        pass
    return -1


def write_receipts(payload: Dict[str, Any]) -> None:
    VAULT.mkdir(parents=True, exist_ok=True)
    body_json = json.dumps(payload, indent=2)
    body_md = (
        f"# Driver Judgment Pulse ? {payload['ts']}\n\n"
        f"**Color:** {payload['color']}  \n"
        f"**Summary:** {payload['summary']}  \n"
        f"**Thread:** `{THREAD}`  \n\n"
        f"| Check | rc | ok |\n|-------|----|----|\n"
        + "\n".join(
            f"| {c['name']} | {c['rc']} | {c['ok']} |"
            for c in payload.get("checks_list") or []
        )
        + f"\n\n**Backlog open:** {payload.get('backlog_open')}  \n"
        f"**Receipt JSON:** `{RECEIPT_JSON}`  \n\n"
        f"Escalate only on **RED**. YELLOW = advisory receipt.\n"
        f"Canon: [[Operations/Grok-Thread-Architecture-Judgment-CANONICAL-2026-07-18]] ?8\n"
    )
    if atomic_write_json:
        atomic_write_json(RECEIPT_JSON, payload, indent=2)
    else:
        RECEIPT_JSON.write_text(body_json + "\n", encoding="utf-8")
    if atomic_write_text:
        atomic_write_text(RECEIPT_MD, body_md)
    else:
        RECEIPT_MD.write_text(body_md, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Driver/Judgment one-shot pulse")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="YELLOW also exits 1")
    args = ap.parse_args()

    checks_order = [
        ("stack_snapshot", ["stack_snapshot.py"]),
        ("local_offline", ["local_offline_mode_check.py", "--no-smoke"]),
        ("loop_registry", ["loop_registry_lint.py"]),
        ("canon_conflict", ["canon_conflict_lint.py"]),
        ("judgment_backlog", ["judgment_backlog.py", "--list"]),
        # measure-only permanence sensor (exit 1 on Admin residual is OK ? classify uses receipt)
        ("single_stack", ["stack_single_instance_audit.py"]),
    ]
    checks: Dict[str, Dict[str, Any]] = {}
    checks_list: List[Dict[str, Any]] = []
    for name, argv in checks_order:
        # backlog is informational only
        timeout = 90 if name not in ("judgment_backlog",) else 30
        if name == "single_stack":
            timeout = 120
        c = run_check(name, argv, timeout=timeout)
        checks[name] = c
        checks_list.append(c)

    color, summary, reds = classify(checks)
    # backlog failures never red
    b_open = backlog_open_count(checks.get("judgment_backlog") or {})

    ss_rec = load_json(Path(r"D:\HermesData\logs\stack_single_instance_audit_latest.json"))
    single_stack_surface = {
        "all_roles_single": ss_rec.get("all_roles_single"),
        "ok": ss_rec.get("ok"),
        "violations": ss_rec.get("violations") or [],
        "roles": {
            k: {
                "single": (v or {}).get("single_instance"),
                "health": (v or {}).get("health"),
                "listeners": (v or {}).get("listeners"),
                "note": (v or {}).get("note"),
            }
            for k, v in (ss_rec.get("roles") or {}).items()
            if isinstance(v, dict)
        },
    }

    payload: Dict[str, Any] = {
        "ts": utc(),
        "color": color,
        "summary": summary,
        "thread": THREAD,
        "red_reasons": reds,
        "backlog_open": b_open,
        "single_stack": single_stack_surface,
        "checks": {k: {"rc": v.get("rc"), "ok": v.get("ok")} for k, v in checks.items()},
        "checks_list": [
            {"name": c["name"], "rc": c["rc"], "ok": c["ok"], "cmd": c["cmd"]}
            for c in checks_list
        ],
        "receipts": {
            "stack_snapshot": str(VAULT / "stack-snapshot-latest.json"),
            "local_offline": str(VAULT / "local-offline-mode-latest.json"),
            "loop_registry": str(VAULT / "loop-registry-lint-latest.json"),
            "canon_conflict": str(VAULT / "canon-conflict-latest.json"),
            "single_stack": str(Path(r"D:\HermesData\logs\stack_single_instance_audit_latest.json")),
            "this_json": str(RECEIPT_JSON),
            "this_md": str(RECEIPT_MD),
        },
        "actions": {
            "GREEN": "none (silent)",
            "YELLOW": "receipt only; no Jeff ping unless recurring",
            "RED": "surface in Driver thread; propose_recovery if symptom clear",
        },
        "never": [
            "taskkill gateway",
            "silo multi-hour land from Driver",
            "flip orchestrator_enabled without Jeff C",
            "invent KPIs",
            "start gateway while single_stack green",
        ],
        "seal": "driver-judgment-pulse-v2-2026-07-22",
    }
    write_receipts(payload)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{color} | {summary}")
        for c in checks_list:
            print(f"  {c['name']}: rc={c['rc']} ok={c['ok']}")
        print(f"  backlog_open={b_open}")
        print(f"  receipt={RECEIPT_JSON}")

    if color == "RED":
        return 1
    if color == "YELLOW" and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
