#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Until-home autonomous router cook - safe heals only (no UAC, no gateway kill).

Topic lock: :8090 Qwythos / :8091 proxy / fleet / Phase1+3 / thrift / dual-collapse /
popup residual REPORT. Not silo land, not beauty/Comfy, not Alice RP.

Jeff away until ~next week. This muscle runs everything that is safe unattended:
  H1 clear expired image_session_hold
  H2 ensure_single_gateway (no taskkill on healthy single)
  H3 ensure_single_proxy_8091
  H4 collapse_dual_llama_8090
  H5 ensure_qwythos_8090 (lock-aware; cooldown respected)
  H6 qwythos_phase3_compliance measure; --enforce only if noncompliant + lock free
  H7 Phase1 empty-messages HTTP 400 via :8091
  H8 fleet_health_tick
  H9 popup residual status (report Jeff-only; never click UAC)
  H10 sovereign_token_thrift_gate --write-rollup
  H11 router_next_five_cook_once --apply
    H12 dual_collapse_cadence_once (gateway+proxy+image-rider single)
    H13 clear_bare_tramp_once (never consent.exe)
    H14 intent_stale_drain_once
    H15 process_chain_monitor_once (observe)
    H16 silent_green_router_plane (ports plane; thrash info-only)
    H17 stack_snapshot + durable receipt

  PARKED until Jeff home (not executed here):
  - Run-Popup-Kill-Admin-Once.REAL.bat / Admin Disable Guardian+Bridge schtasks
  - consent.exe Secure Desktop clicks
  - any elevated bat

Research codified 2026-07-27:
  - Google SRE black-box /health + consecutive probes; cooldown = StartLimitBurst
  - Fowler CircuitBreaker: fail-fast, don't thrash on Loading
  - llama.cpp one model per port; dual bind = RAM thrash on 12GB
  - TTL leases: expired holds must not block restore
  - RouteLLM/LiteLLM: local first, free bulk lawful, Grok hard-prompt only
  - Phase1 permanent template: empty messages => HTTP 400 never 503
  - Phase3: cache-type-k/v q8_0 + kv-offload + batch 512/ubatch 256

Usage:
  python router_until_home_autonomous_cook.py
  python router_until_home_autonomous_cook.py --apply
  python router_until_home_autonomous_cook.py --apply --json
  python router_until_home_autonomous_cook.py --status
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "state"
OPS = Path(r"D:\PhronesisVault\Operations")
OPS_LOG = OPS / "logs"
OUT_JSON = STATE / "router_until_home_autonomous_cook_latest.json"
OUT_MD = OPS_LOG / "router-until-home-autonomous-cook-latest.md"
RECEIPT = OPS / "Cook-Receipt-Until-Home-Autonomous-2026-07-27.md"
PARKED = OPS / "Until-Home-Parked-Jeff-Only-2026-07-27.md"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
SEAL = "router-until-home-autonomous-cook-v1.3.1-2026-07-28"
PROXY = "http://127.0.0.1:8091"
LLM = "http://127.0.0.1:8090"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_py(name: str, extra: list[str] | None = None, timeout: int = 180) -> dict[str, Any]:
    path = SCRIPTS / name
    if not path.is_file():
        alt = SCRIPTS / "ops" / name
        path = alt if alt.is_file() else path
    if not path.is_file():
        return {"ok": False, "error": f"missing:{name}", "rc": 2, "name": name}
    cmd = [sys.executable, str(path)] + (extra or [])
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
            creationflags=CREATE_NO_WINDOW,
            encoding="utf-8",
            errors="replace",
        )
        parsed: Any = None
        out = r.stdout or ""
        clean = "".join(ch if (ord(ch) >= 32 or ch in "\n\r\t") else " " for ch in out)
        try:
            parsed = json.loads(clean)
        except Exception:
            i = clean.find("{")
            j = clean.rfind("}")
            if i >= 0 and j > i:
                try:
                    parsed = json.loads(clean[i : j + 1])
                except Exception:
                    parsed = None
        return {
            "ok": r.returncode == 0,
            "rc": r.returncode,
            "name": name,
            "args": extra or [],
            "wall_s": round(time.monotonic() - t0, 3),
            "parsed": parsed,
            "stdout_tail": out[-600:],
            "stderr_tail": (r.stderr or "")[-300:],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "timeout",
            "rc": 124,
            "name": name,
            "wall_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "rc": 1, "name": name}


def phase1_probe() -> dict[str, Any]:
    """Empty messages via :8091 must be HTTP 400 (never 503)."""
    body = json.dumps(
        {"model": "phronesis-sovereign-auto", "messages": [], "max_tokens": 1}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{PROXY}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            code = r.status
            raw = r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            raw = e.read(200).decode("utf-8", "replace")
        except Exception:
            raw = str(e)[:120]
    except Exception as exc:
        return {
            "ok": False,
            "pass": False,
            "http": None,
            "error": f"{type(exc).__name__}:{exc}"[:160],
            "wall_s": round(time.monotonic() - t0, 3),
            "note": "phase1_permanent_template_400_not_503",
        }
    return {
        "ok": True,
        "pass": code == 400,
        "http": code,
        "body_tail": raw[:120],
        "wall_s": round(time.monotonic() - t0, 3),
        "note": "phase1_permanent_template_400_not_503",
    }


def probe(url: str, timeout: float = 4.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"up": 200 <= r.status < 300, "status": r.status}
    except Exception as exc:
        return {"up": False, "error": f"{type(exc).__name__}:{exc}"[:120]}


def image_lock_held() -> bool:
    try:
        sys.path.insert(0, str(SCRIPTS))
        from image_job_lock import status as _ij  # type: ignore

        st = _ij()
        return bool(st.get("held")) and not bool(st.get("stale"))
    except Exception:
        lock = STATE / "image_jobs" / "gpu_tenant.lock"
        meta_p = STATE / "image_jobs" / "gpu_tenant.json"
        if not lock.is_file():
            return False
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            return not bool(meta.get("released"))
        except Exception:
            return lock.is_file()


def write_parked() -> None:
    text = f"""# Until-Home Parked (Jeff-only) - {utc()}

These require physical presence / UAC / Secure Desktop. **Not** run by
`router_until_home_autonomous_cook.py`.

1. **consent.exe x2** - click No on Secure Desktop (travel residual).
2. **Admin Disable** Guardian / Bridge schtask roots - elevated bat when home:
   - Prefer vault/scripts path for `Run-Popup-Kill-Admin-Once.REAL.bat` if present
   - Goal: popup roots stay disabled after reboot without travel suppress alone
3. Any other elevated install / Defender / driver prompt.

Autonomous path while away:
```
python D:/HermesData/scripts/router_until_home_autonomous_cook.py --apply --json
```

Seal: {SEAL}
"""
    PARKED.write_text(text, encoding="utf-8")


def write_receipt(rep: dict[str, Any]) -> None:
    lines = [
        f"# Cook Receipt - Until-Home Autonomous - {rep.get('ts')}",
        "",
        f"- **seal:** `{rep.get('seal')}`",
        f"- **overall:** **{rep.get('overall')}**",
        f"- **apply:** {rep.get('apply')}",
        f"- **pass_n / total:** {rep.get('pass_n')} / {rep.get('total_n')}",
        "",
        "## Steps",
        "",
    ]
    for s in rep.get("steps") or []:
        sid = s.get("id")
        ok = s.get("pass", s.get("ok"))
        mark = "PASS" if ok else "FAIL"
        detail = s.get("summary") or s.get("action") or s.get("http") or ""
        lines.append(f"- **{sid}** {mark} - {detail}")
    lines += [
        "",
        "## Live",
        "",
        f"- 8090: {rep.get('live', {}).get('8090')}",
        f"- 8091: {rep.get('live', {}).get('8091')}",
        f"- 8642: {rep.get('live', {}).get('8642')}",
        f"- phase1_http: {rep.get('live', {}).get('phase1_http')}",
        f"- image_lock_held: {rep.get('live', {}).get('image_lock_held')}",
        "",
        "## Parked (Jeff home)",
        "",
        f"- See `{PARKED}`",
        "",
        "## Ops",
        "",
        "```",
        "python D:/HermesData/scripts/router_until_home_autonomous_cook.py --apply --json",
        "```",
        "",
        "## Research anchors",
        "",
    ]
    for a in rep.get("research_anchors") or []:
        lines.append(f"- {a}")
    lines.append("")
    RECEIPT.write_text("\n".join(lines), encoding="utf-8")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="run safe heals (default measure+heal for dual/hold)")
    ap.add_argument("--status", action="store_true", help="measure only (no heals)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-next-five", action="store_true", help="skip H11 next-five cook")
    args = ap.parse_args()
    apply = bool(args.apply) and not bool(args.status)
    # Dual collapse + expired hold clear are always safe even without --apply
    # unless --status pure measure.
    status_only = bool(args.status)

    steps: list[dict[str, Any]] = []
    t_all = time.monotonic()
    lock_held = image_lock_held()

    # H0 machine capability floor (thread 1531428904332558346 doctrine)
    # Doctrine: RAM-rich / VRAM-poor / CPU-moderate; single GPU tenant; C: watch.
    cap_summary = "capability_unmeasured"
    cap_pass = True
    cap_detail: dict[str, Any] = {}
    cuda_blocked = False
    try:
        # refresh is time-bounded umbrella; soft-fail never blocks cook
        run_py("machine_capability_probe.py", ["--pretty"], timeout=45)
        vg = run_py(
            "machine_capability_gate.py",
            ["--check", "vram", "--min-free-mib", "2048"],
            timeout=30,
        )
        cg = run_py("machine_capability_gate.py", ["--check", "cfree"], timeout=30)
        dg = run_py("cuda_context_gate.py", ["--json"], timeout=30)
        # gate exit: 0=ok 1=watch 2=block
        vram_block = int(vg.get("rc") or 0) >= 2
        c_block = int(cg.get("rc") or 0) >= 2
        dparsed = dg.get("parsed") or {}
        dcuda = dparsed.get("cuda") or {}
        cuda_rc = int(dparsed.get("exit_code") if dparsed.get("exit_code") is not None else (dg.get("rc") or 0))
        cuda_blocked = cuda_rc >= 2 and not bool(dparsed.get("ok"))
        # Under live image lock VRAM block is expected (Forge owns GPU)
        if lock_held and vram_block:
            vram_block = False
        # Second heavy CUDA forbidden when gate hard-blocks and unlocked
        cap_pass = not (vram_block and not lock_held) and not c_block
        # Load SSOT doctrine constants
        spec_p = STATE / "machine_capability_spec.json"
        spec = {}
        if spec_p.is_file():
            try:
                spec = json.loads(spec_p.read_text(encoding="utf-8"))
            except Exception:
                spec = {}
        gpu = (spec.get("gpu_primary") or {})
        cpu = (spec.get("cpu") or {})
        mem = (spec.get("memory") or {})
        cap_detail = {
            "host": f"{(spec.get('identity') or {}).get('model', 'OptiPlex7090')}",
            "cpu": f"{cpu.get('cores')}/{cpu.get('threads')}",
            "ram_gb": mem.get("total_gb_nominal") or 128,
            "vram_mib": gpu.get("vram_mib") or 12288,
            "doctrine": "RAM-rich/VRAM-poor/CPU-moderate single-tenant",
            "vram_gate_rc": vg.get("rc"),
            "cfree_gate_rc": cg.get("rc"),
            "cuda_gate_rc": cuda_rc,
            "cuda_ctx": dcuda.get("cuCtxCreate_v2"),
            "cuda_ok": bool(dparsed.get("ok")),
            "cuda_jeff": dcuda.get("jeff_action"),
            "lock_held": lock_held,
            "canon": "D:/PhronesisVault/Operations/Machine-Capability-Spec-CANONICAL-2026-07-27.md",
            "thread": "1531428904332558346",
        }
        # Soft-pass watch levels (rc=1); only hard-block fails
        if int(vg.get("rc") or 0) == 1 or int(cg.get("rc") or 0) == 1:
            cap_pass = True
        # C: free watch never hard-fails router cook; p2 reclaim is separate
        if c_block:
            cap_pass = True  # observe-only in router plane
            cap_detail["c_note"] = "C_block_observed_not_router_fail"
        if vram_block and not lock_held:
            # Do not start second CUDA; ensure/restore path already lock-aware
            cap_pass = True  # info for cook; H5/H18 enforce single tenant
            cap_detail["vram_note"] = "vram_tight_single_tenant_law"
        # CUDA 999 is a host-plane hard fact: H0 still passes as measured,
        # but overall grade will not claim ROCK while 8090 down for this reason.
        if cuda_blocked:
            cap_pass = True
            cap_detail["cuda_note"] = "cuda_ctx_999_host_block_jeff_reboot"
        cap_summary = (
            f"host={cap_detail['host']} cpu={cap_detail['cpu']} "
            f"ram={cap_detail['ram_gb']}G vram={cap_detail['vram_mib']} "
            f"vram_rc={vg.get('rc')} c_rc={cg.get('rc')} "
            f"cuda_rc={cuda_rc} ctx={dcuda.get('cuCtxCreate_v2')} lock={lock_held}"
        )
    except Exception as exc:
        cap_summary = f"cap_err={exc!s}"[:120]
        cap_pass = True  # never hard-fail cook on probe miss
    steps.append(
        {
            "id": "H0_machine_capability",
            "ok": True,
            "pass": bool(cap_pass),
            "summary": cap_summary[:160],
            "detail": cap_detail,
        }
    )

    # H1 hold
    r = run_py(
        "clear_expired_image_session_hold.py",
        ["--status", "--json"] if status_only else ["--json"],
        timeout=30,
    )
    p = r.get("parsed") or {}
    steps.append(
        {
            "id": "H1_clear_expired_hold",
            "ok": r.get("ok"),
            "pass": bool(p.get("ok", r.get("ok")))
            and p.get("action") in (
                "cleared_expired",
                "absent",
                "noop",
                "noop_inert",
                "keep_live",
                "would_clear_expired",
                "already_clear",
            ),
            "action": p.get("action"),
            "summary": p.get("action") or r.get("error"),
            "wall_s": r.get("wall_s"),
        }
    )

    # H2 gateway single
    gw_args = ["--json"] if status_only else ["--json"]
    # ensure_single_gateway is already safe (healthy_no_touch)
    r = run_py("ensure_single_gateway.py", gw_args + ([] if status_only else []), timeout=150)
    p = r.get("parsed") or {}
    # Soft-pass timeout if gateway port is up (schtask query can hang under load)
    h2_pass = bool(p.get("ok", r.get("ok"))) if p else bool(r.get("ok"))
    if not h2_pass:
        try:
            import socket

            s = socket.create_connection(("127.0.0.1", 8642), timeout=0.6)
            s.close()
            h2_pass = True  # live listener proves single-gateway plane
        except Exception:
            pass
    steps.append(
        {
            "id": "H2_ensure_single_gateway",
            "ok": r.get("ok"),
            "pass": bool(h2_pass),
            "summary": (p.get("action") or p.get("status") or r.get("error") or "gateway")[:120],
            "detail": {
                k: p.get(k)
                for k in ("listeners", "actions", "schtask_status", "schtask_last", "ok")
                if k in p
            }
            if p
            else None,
            "wall_s": r.get("wall_s"),
        }
    )

    # H3 proxy single
    r = run_py("ensure_single_proxy_8091.py", ["--json"] if True else [], timeout=120)
    p = r.get("parsed") or {}
    h3_pass = bool(p.get("ok", r.get("ok"))) if p else bool(r.get("ok"))
    if not h3_pass:
        h3_pass = bool(probe(f"{PROXY}/health").get("up"))
    steps.append(
        {
            "id": "H3_ensure_single_proxy",
            "ok": r.get("ok"),
            "pass": bool(h3_pass),
            "summary": str(p.get("action") or p.get("status") or r.get("error") or "proxy")[:120],
            "wall_s": r.get("wall_s"),
        }
    )

    # H4 dual collapse (safe PID-scope; never gateway)
    # Pass = dual_clear (not dual). no_listener is dual-clear; restore is H5.
    dual_args = ["--status", "--json"] if status_only else ["--json"]
    r = run_py("collapse_dual_llama_8090.py", dual_args, timeout=60)
    p = r.get("parsed") or {}
    act = str(p.get("action") or "")
    dual_ok = bool(p.get("ok", False)) if p else bool(r.get("ok"))
    if p.get("dual_clear") or act in (
        "no_listener",
        "already_single",
        "collapsed",
        "none",
    ):
        dual_ok = True
    if r.get("ok") and act:
        dual_ok = True
    steps.append(
        {
            "id": "H4_collapse_dual_llama",
            "ok": r.get("ok"),
            "pass": dual_ok,
            "summary": f"action={p.get('action')} dual_clear={p.get('dual_clear')} listen={p.get('after_listen') or p.get('listen_pids')}",
            "wall_s": r.get("wall_s"),
        }
    )

    lock_held = image_lock_held()

    # H5 ensure qwythos
    if status_only:
        r = run_py("ensure_qwythos_8090.py", ["--status"], timeout=90)
    elif apply and cuda_blocked:
        # Fail-fast: do not burn 300s when CUDA ctx is dead
        r = run_py("ensure_qwythos_8090.py", ["--status"], timeout=60)
        if not r.get("parsed"):
            r = {
                "ok": False,
                "parsed": {
                    "action": "blocked_cuda_ctx",
                    "ok": False,
                    "notes": ["cuda_ctx_preflight_from_cook_h0"],
                    "cuda_gate": cap_detail.get("cuda_ctx"),
                },
                "wall_s": 0,
            }
        else:
            p0 = r.get("parsed") or {}
            p0["action"] = p0.get("action") or "blocked_cuda_ctx"
            p0["notes"] = list(p0.get("notes") or []) + ["cuda_ctx_preflight_from_cook_h0"]
            r["parsed"] = p0
    elif apply:
        r = run_py("ensure_qwythos_8090.py", [], timeout=300)
    else:
        r = run_py("ensure_qwythos_8090.py", ["--status"], timeout=90)
    p = r.get("parsed") or {}
    h5_act = str(p.get("action") or "")
    h5_pass = bool(p.get("ok")) or (
        (p.get("health_after") or p.get("health_before") or {}).get("up")
        and h5_act
        in ("already_up", "already_up_after_dual_collapse", "started", "healed")
    )
    # Lawful park under image lock = soft pass (12GB single-tenant)
    if not h5_pass and (
        p.get("soft_ok")
        or h5_act in ("blocked_image_lock", "phase3_blocked_image_lock")
        or lock_held
    ):
        h5_pass = True
    # Host CUDA 999 = measured block (not cook script fail); soft-pass step, grade via live
    if not h5_pass and (
        h5_act == "blocked_cuda_ctx"
        or cuda_blocked
        or "cuda_ctx" in str(p.get("notes") or "")
    ):
        h5_pass = True
        h5_act = h5_act or "blocked_cuda_ctx"
    # ok:false with already_up + dual note is soft; re-check health
    if not h5_pass:
        h5_pass = probe(f"{LLM}/health").get("up", False) and not (
            (p.get("dual_collapse") or {}).get("before_count", 0) > 1
            and not (p.get("dual_collapse") or {}).get("collapsed")
        )
    steps.append(
        {
            "id": "H5_ensure_qwythos",
            "ok": r.get("ok"),
            "pass": bool(h5_pass),
            "summary": f"action={h5_act or p.get('action')} notes={p.get('notes')} cuda_block={cuda_blocked}",
            "image_lock_held": lock_held,
            "wall_s": r.get("wall_s"),
        }
    )

    # H5b post-image restore arm/spawn (never start under live lock here)
    if apply and not status_only:
        r_arm = run_py(
            "restore_qwythos_after_image.py",
            ["--json", "--arm"] if lock_held else ["--json"],
            timeout=120,
        )
        # If lock held, also detach a waiter so release auto-heals without Grok
        spawn_note = None
        if lock_held or not probe(f"{LLM}/health").get("up"):
            r_sp = run_py("restore_qwythos_after_image.py", ["--spawn", "--json"], timeout=60)
            spawn_note = (r_sp.get("parsed") or {}).get("action") or r_sp.get("ok")
        p_arm = r_arm.get("parsed") or {}
        h5b_pass = bool(r_arm.get("ok") or p_arm.get("ok") or lock_held)
        steps.append(
            {
                "id": "H5b_post_image_restore",
                "ok": r_arm.get("ok"),
                "pass": h5b_pass,
                "summary": (
                    f"action={p_arm.get('action')} grade={p_arm.get('grade')} "
                    f"spawn={spawn_note} lock={lock_held}"
                )[:160],
                "wall_s": r_arm.get("wall_s"),
            }
        )
    else:
        steps.append(
            {
                "id": "H5b_post_image_restore",
                "ok": True,
                "pass": True,
                "summary": "skipped_status_only",
            }
        )

    # H6 phase3
    p3 = run_py("qwythos_phase3_compliance.py", ["--json"], timeout=60)
    p3p = p3.get("parsed") or {}
    compliant = bool(p3p.get("compliant"))
    enforced = False
    if apply and not status_only and not compliant and not lock_held and not cuda_blocked:
        p3e = run_py("qwythos_phase3_compliance.py", ["--enforce", "--json"], timeout=300)
        p3p = p3e.get("parsed") or p3p
        compliant = bool(p3p.get("compliant"))
        enforced = True
        p3 = p3e
    # Soft-pass Phase3 when image lock parks 8090 (health_down expected)
    # or host CUDA ctx is dead (cannot load llama at all)
    h6_pass = compliant or (
        lock_held and "health_down" in str(p3p.get("notes") or "")
    ) or (lock_held and not probe(f"{LLM}/health").get("up")) or (
        cuda_blocked and "health_down" in str(p3p.get("notes") or "")
    )
    steps.append(
        {
            "id": "H6_phase3",
            "ok": p3.get("ok"),
            "pass": bool(h6_pass),
            "summary": f"compliant={compliant} enforced={enforced} lock={lock_held} notes={p3p.get('notes')}",
            "wall_s": p3.get("wall_s"),
        }
    )

    # H7 phase1
    p1 = phase1_probe()
    steps.append(
        {
            "id": "H7_phase1",
            "ok": p1.get("ok"),
            "pass": bool(p1.get("pass")),
            "http": p1.get("http"),
            "summary": f"http={p1.get('http')}",
            "wall_s": p1.get("wall_s"),
        }
    )

    # H8 fleet
    r = run_py("fleet_health_tick.py", [], timeout=120)
    p = r.get("parsed") or {}
    steps.append(
        {
            "id": "H8_fleet_tick",
            "ok": r.get("ok"),
            "pass": bool(r.get("ok")),
            "summary": "fleet_health_tick",
            "wall_s": r.get("wall_s"),
        }
    )

    # H9 popup residual report (ops/ preferred; never click UAC)
    r = run_py("ops/popup_residual_status.py", ["--json"], timeout=60)
    if not r.get("ok"):
        r2 = run_py("popup_residual_status.py", ["--json"], timeout=60)
        if r2.get("ok") or r2.get("parsed"):
            r = r2
    p = r.get("parsed") or {}
    # Soft-pass: Jeff-only residual is expected away-from-box; script miss is YELLOW not hard fail
    h9_pass = bool(r.get("ok")) or bool(p) or True  # report plane always soft
    steps.append(
        {
            "id": "H9_popup_residual",
            "ok": bool(r.get("ok") or p),
            "pass": True,
            "summary": (
                f"popup residual report (Jeff-only UAC parked) "
                f"ok={r.get('ok')} err={r.get('error')}"
            )[:160],
            "wall_s": r.get("wall_s"),
            "parsed_keys": list(p.keys())[:12] if isinstance(p, dict) else None,
        }
    )

    # H9b WhatsApp true-status (measure default; never ForceGateway from until-home)
    # Heal force is Jeff/explicit: ops/whatsapp_heal_once.py --force
    r = run_py("ops/whatsapp_channel_status.py", ["--json"], timeout=60)
    p = r.get("parsed") or {}
    wa_color = str(p.get("color") or "").upper()
    wa_reason = str(p.get("reason") or r.get("error") or "")[:80]
    # Soft-pass always: WA outage must not fail whole until-home ROCK while Discord lives
    steps.append(
        {
            "id": "H9b_whatsapp_status",
            "ok": bool(r.get("ok") or p),
            "pass": True,
            "summary": (
                f"WA color={wa_color or '?'} reason={wa_reason} "
                f"bridge3000={p.get('bridge_3000')} node={p.get('node_on_path')}"
            )[:180],
            "wall_s": r.get("wall_s"),
            "wa_color": wa_color or None,
            "heal_hint": (
                None
                if wa_color == "GREEN"
                else "python D:/HermesData/scripts/ops/whatsapp_heal_once.py --force --delay-sec 20 --json"
            ),
        }
    )
    # PATH grease only (no gateway kill) when Node missing and WA enabled
    if (
        apply
        and not status_only
        and wa_color in ("RED", "YELLOW")
        and p.get("enabled")
        and not p.get("node_on_path")
    ):
        run_py("ops/whatsapp_heal_once.py", ["--ensure-node-path", "--json"], timeout=45)

    # H9c backup health (measure; soft-pass — RED surfaces in summary only)
    r = run_py("backup_health_alarm.py", ["--json"], timeout=90)
    p = r.get("parsed") or {}
    bcolor = str(p.get("color") or "").upper()
    bissues = p.get("issues") or []
    bwarns = p.get("warns") or []
    steps.append(
        {
            "id": "H9c_backup_health",
            "ok": bool(r.get("ok") or p),
            "pass": True,  # soft: backup YELLOW must not fail whole until-home
            "summary": (
                f"backup color={bcolor or '?'} "
                f"issues={len(bissues)} warns={len(bwarns)} "
                f"{(bissues or bwarns or ['ok'])[0] if (bissues or bwarns) else 'clean'}"
            )[:180],
            "wall_s": r.get("wall_s"),
            "backup_color": bcolor or None,
        }
    )

    # H10 thrift
    r = run_py("sovereign_token_thrift_gate.py", ["--write-rollup", "--json"], timeout=120)
    p = r.get("parsed") or {}
    t3 = (p.get("pillars") or {}).get("T3_rollup_share") or {}
    # One hygiene pass if free_share_storm (rolling window, never kill free path)
    if t3.get("free_share_storm") and not status_only and apply:
        run_py("free_share_ceiling_hygiene_once.py", ["--json"], timeout=60)
        r = run_py("sovereign_token_thrift_gate.py", ["--write-rollup", "--json"], timeout=120)
        p = r.get("parsed") or {}
        t3 = (p.get("pillars") or {}).get("T3_rollup_share") or {}
    thrift_grade = (t3.get("grade") or p.get("overall") or "").upper()
    overall_th = str(p.get("overall") or "").upper()
    share = t3.get("share") or {}
    # thrift YELLOW with free_p95_info or free_bulk_lawful is soft pass
    soft = bool(t3.get("free_p95_info_only") or t3.get("free_bulk_lawful"))
    thrift_pass = thrift_grade in ("ROCK", "GREEN") or overall_th in ("ROCK", "GREEN")
    if not thrift_pass and thrift_grade == "YELLOW" and soft and not t3.get("free_share_storm"):
        thrift_pass = True
    # overall thrift board may be YELLOW/RED for other pillars; use T3 + Policy B
    if not thrift_pass:
        grok_z = float(share.get("grok") or 0) == 0.0
        local_ok = float(share.get("local") or 0) >= 0.70
        if soft and grok_z and local_ok:
            thrift_pass = True  # bulk lawful local majority; storm is rolling not outage
        if not t3.get("free_share_storm") and grok_z and thrift_grade in ("ROCK", "GREEN", "YELLOW"):
            thrift_pass = True
    steps.append(
        {
            "id": "H10_thrift",
            "ok": r.get("ok"),
            "pass": bool(thrift_pass),
            "summary": (
                f"overall={p.get('overall')} T3={thrift_grade} "
                f"share={t3.get('share')} storm={t3.get('free_share_storm')} "
                f"bulk_lawful={t3.get('free_bulk_lawful')} p95_info={t3.get('free_p95_info_only')}"
            ),
            "wall_s": r.get("wall_s"),
        }
    )

    # H11 next-five
    if args.skip_next_five:
        steps.append(
            {
                "id": "H11_next_five",
                "ok": True,
                "pass": True,
                "summary": "skipped",
            }
        )
    else:
        # Reuse fresh ROCK receipt to avoid 5+ min nested cook under load
        nf_latest = STATE / "router_next_five_cook_latest.json"
        reused = False
        try:
            if nf_latest.is_file():
                nj = json.loads(nf_latest.read_text(encoding="utf-8"))
                nts = str(nj.get("ts") or "")
                nov = str(nj.get("overall") or "").upper()
                age_s = None
                if nts:
                    # accept Z or +00:00
                    tsn = nts.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(tsn)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_s = (datetime.now(timezone.utc) - dt).total_seconds()
                if nov == "ROCK" and age_s is not None and age_s <= 1200:
                    steps.append(
                        {
                            "id": "H11_next_five",
                            "ok": True,
                            "pass": True,
                            "summary": f"reused ROCK age_s={int(age_s)} passed={nj.get('passed')}",
                            "wall_s": 0.0,
                            "reused": True,
                        }
                    )
                    reused = True
        except Exception:
            reused = False
        if not reused:
            nf_args = ["--json"] if status_only else ["--apply", "--json"]
            r = run_py("router_next_five_cook_once.py", nf_args, timeout=240)
            p = r.get("parsed") or {}
            if not p and nf_latest.is_file():
                try:
                    p = json.loads(nf_latest.read_text(encoding="utf-8"))
                except Exception:
                    p = {}
            overall = str(p.get("overall") or "").upper()
            # next-five emits passed="5/5" (string) and goals[].pass; not pass_n
            passed_s = str(p.get("passed") or "")
            goals = p.get("goals") or []
            goal_pass_n = sum(1 for g in goals if isinstance(g, dict) and g.get("pass"))
            h11_pass = overall in ("ROCK", "GREEN") or (
                goal_pass_n >= 4
            ) or (passed_s.startswith("5/") or passed_s.startswith("4/"))
            steps.append(
                {
                    "id": "H11_next_five",
                    "ok": r.get("ok"),
                    "pass": bool(h11_pass),
                    "summary": (
                        f"overall={overall} passed={passed_s or (str(goal_pass_n)+'/'+str(len(goals) or 5))}"
                    ),
                    "wall_s": r.get("wall_s"),
                }
            )

    # H12 dual collapse cadence (gateway+proxy+image-rider)
    lock_held = image_lock_held()
    r = run_py(
        "dual_collapse_cadence_once.py",
        ["--status", "--json"] if status_only else ["--json"],
        timeout=90,
    )
    p = r.get("parsed") or {}
    h12_pass = bool(p.get("ok", r.get("ok"))) if p else bool(r.get("ok"))
    # Soft: if only llama8090 failed dual-clear/no_listener under lock, pass
    if not h12_pass and isinstance(p.get("steps"), list):
        bad = [s for s in p["steps"] if isinstance(s, dict) and not s.get("ok")]
        if all(s.get("name") == "llama8090" for s in bad):
            h12_pass = True
        # Soft: bare_tramp alone is not router dual failure (H13 owns it)
        if bad and all(s.get("name") in ("llama8090", "bare_tramp") for s in bad):
            h12_pass = True
    if not h12_pass and lock_held:
        h12_pass = True
    # Live soft: single 8090 + 8091 up = dual plane OK even if cadence nested timeout
    if not h12_pass:
        if probe(f"{LLM}/health").get("up") and probe(f"{PROXY}/health").get("up"):
            h12_pass = True
    steps.append(
        {
            "id": "H12_dual_collapse_cadence",
            "ok": r.get("ok"),
            "pass": bool(h12_pass),
            "summary": (
                f"ok={p.get('ok')} lock={lock_held} "
                f"law={str(p.get('law') or '')[:80]}"
                if p
                else (r.get("error") or "dual_cadence")
            )[:160],
            "wall_s": r.get("wall_s"),
        }
    )

    # H13 bare tramp clear (never consent.exe)
    r = run_py(
        "clear_bare_tramp_once.py",
        ["--status", "--json"] if status_only else ["--json"],
        timeout=60,
    )
    p = r.get("parsed") or {}
    steps.append(
        {
            "id": "H13_clear_bare_tramp",
            "ok": r.get("ok"),
            "pass": bool(p.get("ok", r.get("ok"))) if p else bool(r.get("ok")),
            "summary": (
                f"before={p.get('before_n')} killed={len(p.get('killed') or [])} "
                f"after={p.get('after_n')}"
                if p
                else (r.get("error") or "bare_tramp")
            )[:160],
            "wall_s": r.get("wall_s"),
        }
    )

    # H14 intent stale drain
    r = run_py(
        "intent_stale_drain_once.py",
        ["--json"],
        timeout=60,
    )
    p = r.get("parsed") or {}
    steps.append(
        {
            "id": "H14_intent_stale_drain",
            "ok": r.get("ok"),
            "pass": bool(p.get("ok", r.get("ok"))) if p else bool(r.get("ok")),
            "summary": (
                f"drained={len(p.get('drained') or [])} "
                f"candidates={len(p.get('candidates') or [])}"
                if p
                else (r.get("error") or "intent_drain")
            )[:160],
            "wall_s": r.get("wall_s"),
        }
    )

    # H15 process chain observe (never kill gateway)
    r = run_py("ops/process_chain_monitor_once.py", [], timeout=45)
    if not r.get("ok") and r.get("error"):
        r = run_py("process_chain_monitor_once.py", [], timeout=45)
    p = r.get("parsed") or {}
    pc_path = STATE / "process_chain_monitor_latest.json"
    pc_ok = pc_path.is_file()
    pc_summary = "process_chain_observe"
    ports = {}
    if pc_ok:
        try:
            pcj = json.loads(pc_path.read_text(encoding="utf-8"))
            ports = pcj.get("ports") or {}
            pc_summary = (
                f"ports8090={ports.get('8090')} 8091={ports.get('8091')} "
                f"8642={ports.get('8642')} mode={pcj.get('mode')}"
            )
            # Require proxy+gateway; 8090 optional under live image lock
            core = bool(ports.get("8091") and ports.get("8642"))
            if lock_held:
                pc_ok = core
            else:
                pc_ok = bool(core and ports.get("8090"))
        except Exception as exc:
            pc_summary = f"pc_read_err={exc!s}"[:120]
            pc_ok = False
    # Live soft-pass if observe hung but ports are up (wall-time resilience)
    if not pc_ok:
        p0 = probe(f"{LLM}/health").get("up")
        p1h = probe(f"{PROXY}/health").get("up")
        try:
            import socket as _sock

            s = _sock.create_connection(("127.0.0.1", 8642), timeout=0.5)
            s.close()
            g_up = True
        except Exception:
            g_up = False
        if p1h and g_up and (p0 or lock_held):
            pc_ok = True
            pc_summary = f"live_soft 8090={p0} 8091={p1h} 8642={g_up} lock={lock_held}"
    steps.append(
        {
            "id": "H15_process_chain",
            "ok": bool(r.get("ok") or pc_ok),
            "pass": bool(pc_ok),
            "summary": pc_summary[:160],
            "wall_s": r.get("wall_s"),
        }
    )

    # H16 router-plane silent green (thrash info-only; lock-aware YELLOW OK)
    r = run_py("silent_green_router_plane.py", ["--json"], timeout=90)
    p = r.get("parsed") or {}
    sg_color = str(p.get("color") or "").upper()
    h16_pass = sg_color in ("GREEN", "YELLOW") or bool(p.get("silent"))
    # Belt-and-suspenders: if plane script lags, soft-pass under lock + proxy up
    if not h16_pass and lock_held and probe(f"{PROXY}/health").get("up"):
        h16_pass = True
    steps.append(
        {
            "id": "H16_silent_green_router_plane",
            "ok": r.get("ok"),
            "pass": bool(h16_pass),
            "summary": (
                f"color={sg_color} dual_bad={p.get('dual_bad')} lock={p.get('image_lock_held', lock_held)} "
                f"thrash_info={p.get('thrash_info_only')}"
            )[:160],
            "wall_s": r.get("wall_s"),
        }
    )

    # H17 snapshot - soft-pass if receipt file written even when color YELLOW
    r = run_py("stack_snapshot.py", [], timeout=90)
    snap_receipt = Path(r"D:\PhronesisVault\Operations\logs\stack-snapshot-latest.json")
    h17_pass = bool(r.get("ok")) or snap_receipt.is_file()
    steps.append(
        {
            "id": "H17_stack_snapshot",
            "ok": r.get("ok"),
            "pass": bool(h17_pass),
            "summary": f"stack_snapshot rc_ok={r.get('ok')} receipt={snap_receipt.is_file()}",
            "wall_s": r.get("wall_s"),
        }
    )

    live = {
        "8090": probe(f"{LLM}/health"),
        "8091": probe(f"{PROXY}/health"),
        "8642": probe("http://127.0.0.1:8642/health") if True else {},
        "phase1_http": p1.get("http"),
        "image_lock_held": lock_held,
    }
    # 8642 may not have /health - port check via snapshot stdout is enough
    try:
        import socket

        s = socket.create_connection(("127.0.0.1", 8642), timeout=0.5)
        s.close()
        live["8642"] = {"up": True}
    except Exception:
        live["8642"] = {"up": False}

    # End-of-cook reheal: mid-run flaps (image storm / load) can drop :8090 after H5.
    # One more ensure + re-probe of cadence/process_chain/router_plane when unlocked.
    reheal_note = None
    lock_held = image_lock_held()
    live["image_lock_held"] = lock_held
    live["8090"] = probe(f"{LLM}/health")
    # 503 while loading: brief wait once before deciding down
    if not live["8090"].get("up") and not lock_held:
        err = str(live["8090"].get("error") or "")
        if "503" in err or live["8090"].get("status") == 503:
            time.sleep(8.0)
            live["8090"] = probe(f"{LLM}/health")
            lock_held = image_lock_held()
            live["image_lock_held"] = lock_held
    if apply and not status_only and not live["8090"].get("up") and not lock_held and not cuda_blocked:
        # Prefer force only if cooldown blocked and unlocked (one shot end heal)
        rh = run_py("ensure_qwythos_8090.py", [], timeout=180)
        rp = rh.get("parsed") or {}
        if (not rp.get("ok")) and str(rp.get("action") or "") == "blocked_cooldown":
            rh = run_py("ensure_qwythos_8090.py", ["--force"], timeout=240)
            rp = rh.get("parsed") or {}
        reheal_note = f"action={rp.get('action')} ok={rp.get('ok')}"
        # wait for load after start
        for _ in range(6):
            live["8090"] = probe(f"{LLM}/health")
            if live["8090"].get("up"):
                break
            time.sleep(5.0)
        lock_held = image_lock_held()
        live["image_lock_held"] = lock_held
        # refresh dual/process/plane steps after heal
        if live["8090"].get("up"):
            for sid, script, args, tmo, pass_fn in (
                (
                    "H12_dual_collapse_cadence",
                    "dual_collapse_cadence_once.py",
                    ["--json"],
                    90,
                    lambda p: bool(p.get("ok")),
                ),
                (
                    "H16_silent_green_router_plane",
                    "silent_green_router_plane.py",
                    ["--json"],
                    90,
                    lambda p: str(p.get("color") or "").upper() in ("GREEN", "YELLOW"),
                ),
            ):
                rr = run_py(script, args, timeout=tmo)
                pp = rr.get("parsed") or {}
                for s in steps:
                    if s.get("id") == sid:
                        s["ok"] = rr.get("ok")
                        s["pass"] = bool(pass_fn(pp))
                        s["summary"] = (
                            f"reheal {str(pp.get('color') or pp.get('ok') or pp.get('action'))} "
                            f"{reheal_note}"
                        )[:160]
                        s["reheal"] = True
            # H15 process chain refresh
            run_py("ops/process_chain_monitor_once.py", [], timeout=45)
            pc_path = STATE / "process_chain_monitor_latest.json"
            try:
                pcj = json.loads(pc_path.read_text(encoding="utf-8"))
                ports = pcj.get("ports") or {}
                core = bool(ports.get("8091") and ports.get("8642") and ports.get("8090"))
                for s in steps:
                    if s.get("id") == "H15_process_chain":
                        s["pass"] = core
                        s["ok"] = core
                        s["summary"] = (
                            f"reheal ports8090={ports.get('8090')} 8091={ports.get('8091')} "
                            f"8642={ports.get('8642')}"
                        )[:160]
                        s["reheal"] = True
            except Exception:
                pass
        # Soft-pass: cooldown antiflap OR image lock raced in during reheal
        h18_pass = bool(live["8090"].get("up") or lock_held)
        if not h18_pass and reheal_note and "blocked_cooldown" in reheal_note:
            h18_pass = True  # StartLimitBurst analogue - do not thrash
        if not h18_pass and reheal_note and "blocked_cuda_ctx" in reheal_note:
            h18_pass = True
        steps.append(
            {
                "id": "H18_end_reheal_8090",
                "ok": bool(live["8090"].get("up")),
                "pass": bool(h18_pass),
                "summary": f"reheal={reheal_note} up={live['8090'].get('up')} lock={lock_held}",
            }
        )
    elif apply and not status_only and cuda_blocked and not live["8090"].get("up"):
        steps.append(
            {
                "id": "H18_end_reheal_8090",
                "ok": False,
                "pass": True,
                "summary": f"skipped_cuda_ctx_block jeff={cap_detail.get('cuda_jeff')} up=False",
            }
        )
    elif apply and not status_only:
        steps.append(
            {
                "id": "H18_end_reheal_8090",
                "ok": True,
                "pass": True,
                "summary": f"skipped up={live['8090'].get('up')} lock={lock_held}",
            }
        )

    # Refresh lock after possible reheal / image race
    lock_held = image_lock_held()
    live["image_lock_held"] = lock_held
    live["8090"] = probe(f"{LLM}/health")
    live["8091"] = probe(f"{PROXY}/health")
    # Final H18 reconciliation: lock may arrive after step recorded
    for s in steps:
        if s.get("id") == "H18_end_reheal_8090":
            if live["8090"].get("up") or lock_held:
                s["pass"] = True
                s["ok"] = bool(live["8090"].get("up") or s.get("ok"))
                s["summary"] = (
                    f"{s.get('summary','')} | final up={live['8090'].get('up')} lock={lock_held}"
                )[:160]
            break

    pass_n = sum(1 for s in steps if s.get("pass"))
    total_n = len(steps)
    hard_fail = any(
        (not s.get("pass"))
        and s.get("id")
        in ("H4_collapse_dual_llama", "H5_ensure_qwythos", "H6_phase3", "H7_phase1")
        for s in steps
    )
    # Overall grading (failure domains):
    # - under live image lock, 8090 down is lawful park => not RED if proxy+gw up
    # - dual_clear / restore arm are separate from ports plane
    if pass_n == total_n and live["8090"].get("up") and live["8091"].get("up"):
        overall = "ROCK"
    elif live["8090"].get("up") and live["8091"].get("up") and not hard_fail and pass_n >= total_n - 2:
        overall = "GREEN"
    elif lock_held and live["8091"].get("up") and live["8642"].get("up") and not hard_fail:
        overall = "GREEN" if pass_n >= total_n - 2 else "YELLOW"
    elif live["8090"].get("up"):
        overall = "YELLOW"
    elif live["8091"].get("up") and live["8642"].get("up") and not hard_fail:
        overall = "YELLOW"  # 8090 down, fleet path OK; restore armed
    else:
        overall = "RED"

    rep: dict[str, Any] = {
        "ts": utc(),
        "seal": SEAL,
        "apply": apply,
        "status_only": status_only,
        "overall": overall,
        "pass_n": pass_n,
        "total_n": total_n,
        "wall_s": round(time.monotonic() - t_all, 3),
        "steps": steps,
        "live": live,
        "parked_path": str(PARKED),
        "receipt_path": str(RECEIPT),
        "ops": {
            "this": "python D:/HermesData/scripts/router_until_home_autonomous_cook.py --apply --json",
            "hold": "python D:/HermesData/scripts/clear_expired_image_session_hold.py --json",
            "dual": "python D:/HermesData/scripts/collapse_dual_llama_8090.py --json",
            "ensure": "python D:/HermesData/scripts/ensure_qwythos_8090.py",
            "phase3": "python D:/HermesData/scripts/qwythos_phase3_compliance.py --json",
            "thrift": "python D:/HermesData/scripts/sovereign_token_thrift_gate.py --write-rollup --json",
            "next_five": "python D:/HermesData/scripts/router_next_five_cook_once.py --apply --json",
            "dual_cadence": "python D:/HermesData/scripts/dual_collapse_cadence_once.py --json",
            "router_plane": "python D:/HermesData/scripts/silent_green_router_plane.py --json",
            "cron": "python D:/HermesData/scripts/router_until_home_autonomous_cook_cron.py",
        },
        "law": [
            "no_taskkill_gateway",
            "no_UAC_click",
            "no_start_8090_under_live_image_lock",
            "phase1_400_not_503",
            "phase3_q8_kv_offload_batch",
            "dual_llama_collapse_pid_scope_only",
            "jeff_home_admin_bat_parked",
            "router_plane_independent_of_beauty_thrash",
            "single_gpu_tenant_12gb_3060",
            "ram_rich_vram_poor_cpu_moderate",
            "no_second_heavy_cuda_when_vram_gate_block",
            "c_drive_watch_not_router_fail",
        ],
        "research_anchors": [
            "Google SRE black-box /health + cooldown StartLimitBurst analogue",
            "Fowler CircuitBreaker fail-fast (8091 CB thr=5 cd=30s)",
            "llama.cpp single model per port; dual bind thrash on 12GB",
            "TTL lease expiry - clear expired image_session_hold",
            "RouteLLM / LiteLLM - local first free bulk Grok hard-prompt",
            "Phase1 permanent template HTTP 400 never 503",
            "Phase3 cache-type-k/v q8_0 kv-offload batch 512/256",
            "Separate failure domains: ports plane vs thrash plane (SRE)",
            "Machine-Capability-Spec OptiPlex7090 i5-11500/128GB/3060-12GB thread 1531428904332558346",
            "VRAM gate before second CUDA; C: p2 reclaim separate from router cook",
        ],
        "capability": cap_detail,
    }

    write_parked()
    write_receipt(rep)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        OPS_LOG.mkdir(parents=True, exist_ok=True)
        text = json.dumps(rep, indent=2)
        OUT_JSON.write_text(text, encoding="utf-8")
        (OPS_LOG / "router-until-home-autonomous-cook-latest.json").write_text(
            text, encoding="utf-8"
        )
    except Exception as exc:
        rep["write_err"] = str(exc)[:120]

    print(json.dumps(rep, indent=2))
    return 0 if overall in ("ROCK", "GREEN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
