#!/usr/bin/env python3
"""One-shot stack snapshot for Discord Hermes (cuts tasklist storms).

W3-P1 2026-07-21:
  - router_color = worst(ports, fleet, proxy_circuit) independent of orch
  - orch_color stays separate (silo continuous / dual thrash)
  - overall = worst(router, orch_for_hub); operator_primary = router_color
  - Always embed thrift rollup + local_tenant (W3-P3/P4)
  - Never trust stale silent-green receipt alone
  - Fleet health freshness (age hours) for opportunistic tier
  - ASCII-only source

Usage:
  python stack_snapshot.py
  python stack_snapshot.py --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_json

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"
PY = sys.executable
VAULT = Path(r"D:\PhronesisVault\Operations\logs")
RECEIPT = VAULT / "stack-snapshot-latest.json"
UNIFIED_COLOR = VAULT / "stack-color-unified-latest.json"
RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2, "UNKNOWN": 1}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def probe(url: str, timeout: float = 2.5) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "stack-snapshot/1.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"up": 200 <= int(resp.status) < 300, "status": int(resp.status)}
    except Exception as e:
        return {"up": False, "error": type(e).__name__}


def count_cmd(substr: str) -> int:
    """Count python/pythonw processes whose CommandLine contains substr."""
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "(Get-CimInstance Win32_Process | Where-Object { "
                    "$_.Name -like 'python*' -and "
                    f"$_.CommandLine -like '*{substr}*' "
                    "}).Count"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return int((r.stdout or "0").strip() or "0")
    except Exception:
        return -1


def last_json(path: Path) -> dict | None:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def worst(colors: list[str]) -> str:
    best = "GREEN"
    for c in colors:
        c = (c or "UNKNOWN").upper()
        if RANK.get(c, 1) > RANK.get(best, 0):
            best = c if c in RANK else "YELLOW"
    return best


def ports_color(ports: dict) -> dict:
    g8090 = bool((ports.get("8090") or {}).get("up"))
    g8091 = bool((ports.get("8091") or {}).get("up"))
    g8642 = bool((ports.get("8642") or {}).get("up"))
    if g8090 and g8091 and g8642:
        return {"color": "GREEN", "summary": "gateway+8091+8090 up", "source": "live_ports"}
    if not g8642:
        return {"color": "RED", "summary": "gateway :8642 down", "source": "live_ports"}
    if g8642 and g8091 and not g8090:
        return {
            "color": "YELLOW",
            "summary": "degraded: gateway+8091 up but llama :8090 down",
            "source": "live_ports",
        }
    return {"color": "YELLOW", "summary": "degraded: partial stack", "source": "live_ports"}


def orch_color() -> dict:
    """v1.3 silent_green plane (orch/silo thrash) - prefer live pulse state."""
    # Prefer state file written by silent_green_pulse, then vault md/json
    candidates = [
        ROOT / "state" / "silent_green_pulse.json",
        VAULT / "silent-green-pulse-latest.json",
    ]
    for path in candidates:
        d = last_json(path)
        if not d:
            continue
        color = d.get("overall") or d.get("color") or d.get("orch_health")
        if color:
            return {
                "color": str(color).upper(),
                "summary": f"orch plane from {path.name}",
                "source": str(path),
                "ts": d.get("at") or d.get("ts"),
                "continuous_live": d.get("continuous_live"),
                "dual_bad": d.get("dual_bad"),
            }
    return {"color": "UNKNOWN", "summary": "no orch pulse receipt", "source": None}


def fleet_color() -> dict:
    """P5: fleet health for ENABLED providers only (registry SSOT).

    W2-P2: also gate on fleet-health-tick-latest.json age (<=6h) and guard ok.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None
    enabled_ids: set[str] = set()
    reg_path = ROOT / "config" / "fleet_registry.yaml"
    if yaml and reg_path.is_file():
        try:
            reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
            for key in ("compute_providers", "context_providers"):
                for item in reg.get(key) or []:
                    if isinstance(item, dict) and item.get("enabled") and item.get("id"):
                        enabled_ids.add(str(item["id"]))
        except Exception:
            enabled_ids = set()

    # W2-P2 tick / guard gate (never auto-enable)
    tick = last_json(VAULT / "fleet-health-tick-latest.json") or {}
    tick_age_h = None
    tick_ts = tick.get("ts") or tick.get("at")
    if tick_ts:
        try:
            t0 = datetime.fromisoformat(str(tick_ts).replace("Z", "+00:00"))
            tick_age_h = (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0
        except Exception:
            tick_age_h = None
    tick_stale = tick_age_h is None or tick_age_h > 6.0
    guard_ok = True
    if isinstance(tick.get("guard"), dict):
        guard_ok = bool(tick["guard"].get("ok") or (tick["guard"].get("summary") or {}).get("ok"))
    if tick and (not guard_ok or tick.get("color") == "RED"):
        return {
            "color": "YELLOW" if guard_ok else "RED",
            "summary": f"fleet tick guard_ok={guard_ok} color={tick.get('color')} age_h={tick_age_h}",
            "source": "fleet-health-tick-latest.json",
            "tick_age_h": tick_age_h,
            "enabled_ids": sorted(enabled_ids),
        }
    if tick_stale and tick:
        return {
            "color": "YELLOW",
            "summary": f"fleet health tick stale age_h={tick_age_h} (max 6h)",
            "source": "fleet-health-tick-latest.json",
            "tick_age_h": tick_age_h,
            "enabled_ids": sorted(enabled_ids),
        }

    state = last_json(VAULT / "fleet-health-state.json") or {}
    providers_map = state.get("providers") if isinstance(state, dict) else {}
    if not isinstance(providers_map, dict):
        providers_map = {}

    up = down = unknown = 0
    ages: list[float] = []
    now = datetime.now(timezone.utc)
    ids_up: list[str] = []
    ids_down: list[str] = []

    def _ingest(pid: str, meta: dict) -> None:
        nonlocal up, down, unknown
        if enabled_ids and pid not in enabled_ids:
            return
        st = str(meta.get("status") or "").lower()
        if st == "up" or meta.get("ok") is True:
            up += 1
            ids_up.append(pid)
        elif st == "down" or meta.get("ok") is False:
            down += 1
            ids_down.append(pid)
        else:
            unknown += 1
        lc = meta.get("last_check")
        if lc:
            try:
                ts = datetime.fromisoformat(str(lc).replace("Z", "+00:00"))
                ages.append((now - ts).total_seconds())
            except Exception:
                pass

    if providers_map:
        for pid, meta in providers_map.items():
            if isinstance(meta, dict):
                _ingest(str(pid), meta)
    else:
        try:
            r = subprocess.run(
                [PY, str(SCRIPTS / "external_fleet_manager.py"), "--status"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(SCRIPTS),
            )
            j = json.loads(r.stdout or "{}")
            for item in (j.get("compute_providers") or []) + (j.get("context_providers") or []):
                hid = str(item.get("id") or "")
                health = item.get("health") or {}
                _ingest(
                    hid,
                    {
                        "status": health.get("status"),
                        "last_check": health.get("last_check"),
                        "ok": health.get("status") == "up",
                    },
                )
        except Exception as exc:
            return {
                "color": "YELLOW",
                "summary": f"fleet status probe failed: {exc}"[:160],
                "source": "external_fleet_manager --status",
                "up": 0,
                "down": 0,
                "enabled_ids": sorted(enabled_ids),
            }

    providers_n = up + down + unknown
    if enabled_ids:
        providers_n = max(providers_n, len(enabled_ids))

    max_age_h = (max(ages) / 3600.0) if ages else None
    stale = max_age_h is not None and max_age_h > 6.0

    if enabled_ids and set(ids_up) >= enabled_ids and not stale:
        color = "GREEN"
        summary = f"fleet all {len(enabled_ids)} enabled UP"
    elif providers_n == 0 and not enabled_ids:
        color = "YELLOW"
        summary = "no fleet providers reported"
    elif down == 0 and up > 0 and not stale:
        color = "GREEN"
        summary = f"fleet {up}/{len(enabled_ids) or providers_n} enabled UP fresh"
    elif up == 0 and enabled_ids:
        color = "RED"
        summary = "fleet all enabled down or unchecked"
    else:
        color = "YELLOW"
        summary = f"fleet degraded up={up} down={down}" + (" stale" if stale else "")

    return {
        "color": color,
        "summary": summary,
        "source": "fleet_health_enabled_only",
        "up": up,
        "down": down,
        "unknown": unknown,
        "providers_n": providers_n,
        "enabled_ids": sorted(enabled_ids),
        "max_age_hours": round(max_age_h, 2) if max_age_h is not None else None,
        "stale_gt_6h": stale,
        "ids_up": ids_up[:12],
        "ids_down": ids_down[:12],
        "tick_age_h": tick_age_h,
        "guard_ok": guard_ok,
        "last_demote": _last_demote_surface(),
    }


def _last_demote_surface() -> dict | None:
    """W4-P3: prefer latest.json, else tail of demote receipts jsonl."""
    for path in (
        VAULT / "fleet-demote-latest.json",
        ROOT / "state" / "fleet-demote-latest.json",
    ):
        d = last_json(path)
        if d:
            return d
    jsonl = VAULT / "fleet-demote-receipts.jsonl"
    try:
        if jsonl.is_file() and jsonl.stat().st_size > 0:
            raw = jsonl.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(raw[-40:]):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    return json.loads(line)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def proxy_circuit_color() -> dict:
    """Proxy :8091 circuit plane for router_color (W3-P1)."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8091/health",
            headers={"User-Agent": "stack-snapshot/1.4"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        cbs = (body.get("circuit_breakers") or {}).get("8090") or {}
        state = str(cbs.get("state") or "unknown").lower()
        force_open = bool(cbs.get("force_open"))
        color = "GREEN"
        if force_open or state in {"open", "half_open"}:
            color = "YELLOW"
        stack = body.get("stack") or {}
        if body.get("status") not in {"GREEN", "OK", "ok", None} and not stack.get(
            "proxy_ready", True
        ):
            color = "RED"
        return {
            "color": color,
            "summary": f"circuit_8090={state} force_open={force_open}",
            "source": "proxy_8091_health",
            "circuit_8090": state,
            "force_open": force_open,
            "failures": cbs.get("failures"),
            "proxy_status": body.get("status"),
        }
    except Exception as exc:
        return {
            "color": "RED",
            "summary": f"proxy health fail: {type(exc).__name__}",
            "source": "proxy_8091_health",
            "error": str(exc)[:160],
        }


def thrift_plane() -> dict:
    """Always-on thrift rollup plane (W3-P3 / W4-P2/P5)."""
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from router_thrift_rollup import write_thrift_rollup

        roll = write_thrift_rollup()
        return {
            "color": str(roll.get("color") or "YELLOW").upper(),
            "summary": f"thrift local={((roll.get('thrift') or {}).get('local'))} "
            f"free={((roll.get('thrift') or {}).get('free'))} "
            f"grok={((roll.get('thrift') or {}).get('grok'))}",
            "source": "router_thrift_rollup",
            "thrift": roll.get("thrift"),
            "share": roll.get("share"),
            "latency_ms": roll.get("latency_ms"),
            "unknown_samples": roll.get("unknown_samples"),
            "notes": roll.get("notes") or [],
            "window_hours": roll.get("window_hours"),
            "provenance_lines": roll.get("provenance_lines"),
        }
    except Exception as exc:
        stale = last_json(VAULT / "router-thrift-rollup-latest.json") or {}
        if stale:
            return {
                "color": str(stale.get("color") or "YELLOW").upper(),
                "summary": "thrift from stale file (builder error)",
                "source": "router-thrift-rollup-latest.json",
                "thrift": stale.get("thrift"),
                "share": stale.get("share"),
                "latency_ms": stale.get("latency_ms"),
                "error": f"{type(exc).__name__}:{exc}"[:160],
            }
        return {
            "color": "YELLOW",
            "summary": f"thrift builder fail: {type(exc).__name__}",
            "source": "router_thrift_rollup",
            "error": str(exc)[:160],
        }


def local_tenant_plane() -> dict:
    """One local tenant status block (W3-P4)."""
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from local_tenant_status import write_status

        st = write_status()
        return {
            "color": str(st.get("color") or "YELLOW").upper(),
            "summary": f"can_serve={st.get('can_serve')} reason={st.get('can_serve_reason')}",
            "source": "local_tenant_status",
            "up": st.get("up"),
            "can_serve": st.get("can_serve"),
            "can_serve_reason": st.get("can_serve_reason"),
            "model_id": st.get("model_id"),
            "ngl": st.get("ngl"),
            "image_lock_held": st.get("image_lock_held"),
            "vram": st.get("vram"),
            "cooldown": st.get("cooldown"),
        }
    except Exception as exc:
        return {
            "color": "YELLOW",
            "summary": f"local_tenant fail: {type(exc).__name__}",
            "source": "local_tenant_status",
            "error": str(exc)[:160],
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fleet-health", action="store_true", help="run live fleet --health (slower)")
    ap.add_argument(
        "--exit-on",
        choices=["router", "overall"],
        default="router",
        help="exit code plane (default router for this lane)",
    )
    args = ap.parse_args()

    ports = {
        "8642": probe("http://127.0.0.1:8642/health"),
        "8091": probe("http://127.0.0.1:8091/health"),
        "8090": probe("http://127.0.0.1:8090/v1/models"),
        "9119": probe("http://127.0.0.1:9119"),
        "3001": probe("http://127.0.0.1:3001/"),
    }

    writers = {
        "continuous": count_cmd("silo_continuous_loop"),
        "orchestrator": count_cmd("silo_orchestrator_tick"),
        "focus": count_cmd("silo_focus_land"),
        "drain": count_cmd("g_to_k_safe_drain"),
        "gateway_run": count_cmd("gateway.run"),
        "gateway_service": count_cmd("hermes_gateway_service"),
        "meta": count_cmd("hermes_meta_watchdog"),
        "note": "counts include venv launcher+child pairs; ~2 per role is normal",
    }

    if args.fleet_health:
        try:
            subprocess.run(
                [PY, str(SCRIPTS / "external_fleet_manager.py"), "--health"],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(SCRIPTS),
            )
        except Exception:
            pass

    pc = ports_color(ports)
    oc = orch_color()
    fc = fleet_color()
    circ = proxy_circuit_color()
    thrift = thrift_plane()
    tenant = local_tenant_plane()

    # W3-P1: router plane independent of orch (silo continuous is out-of-lane)
    router_color = worst([pc.get("color"), fc.get("color"), circ.get("color")])
    # tenant RED softens router to YELLOW (local cannot serve); thrift YELLOW is signal only
    if str(tenant.get("color") or "").upper() == "RED" and router_color == "GREEN":
        router_color = "YELLOW"

    # Hub overall: orch intentional-idle YELLOW does not poison; orch RED still visible
    orch_for_overall = oc.get("color")
    if str(orch_for_overall).upper() == "YELLOW" and not oc.get("dual_bad"):
        orch_for_overall = "GREEN"
    overall = worst([router_color, orch_for_overall])
    stack_color = {
        "ts": utc(),
        "router_color": router_color,
        "operator_primary": router_color,
        "ports_color": pc,
        "orch_color": oc,
        "fleet_color": fc,
        "proxy_circuit_color": circ,
        "thrift_color": thrift,
        "local_tenant_color": tenant,
        "overall": overall,
        "rule": (
            "router_color=worst(ports,fleet,proxy_circuit); "
            "overall=worst(router,orch_for_hub); thrift/tenant are signal planes"
        ),
        "seal": "stack-color-unified-v1.4-w3p1-2026-07-21",
    }

    # Compat: silent_green = ports plane (historical consumers)
    green = {
        "color": pc.get("color"),
        "summary": pc.get("summary"),
        "source": pc.get("source"),
        "router_color": router_color,
        "overall_unified": overall,
        "stale_receipt_color": (last_json(VAULT / "silent-green-pulse-latest.json") or {}).get("color"),
        "stale_receipt_ts": (last_json(VAULT / "silent-green-pulse-latest.json") or {}).get("ts"),
    }

    intent = last_json(VAULT / "intent-queue-latest.json")
    voice = last_json(VAULT / "voice-truth-last.json")
    recovery = last_json(VAULT / "propose-recovery-latest.json")

    six: dict[str, Any] = {}
    try:
        r = subprocess.run(
            [PY, str(SCRIPTS / "silo_discord_six_numbers.py")],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(SCRIPTS),
        )
        for line in (r.stdout or "").splitlines():
            if "=" in line and line[:1].isdigit():
                for part in line.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if v.isdigit():
                            six[k] = int(v)
    except Exception as e:
        six = {"error": str(e)}

    payload = {
        "ts": utc(),
        "schema": "stack_snapshot_v1.4",
        "router_color": router_color,
        "orch_color": oc.get("color"),
        "overall": overall,
        "operator_primary": router_color,
        "ports": ports,
        "process_counts": writers,
        "silent_green": green,
        "stack_color": stack_color,
        "thrift": thrift,
        "local_tenant": tenant,
        "last_intent": {
            "id": (intent or {}).get("id"),
            "status": (intent or {}).get("status"),
            "text": ((intent or {}).get("text") or "")[:80],
        }
        if intent
        else None,
        "last_voice": {
            "path": ((voice or {}).get("audio") or {}).get("path"),
            "from_tool": (voice or {}).get("from_tool"),
        }
        if voice
        else None,
        "last_recovery_class": (recovery or {}).get("class"),
        "silo_six": six,
        "out_of_lane_note": (
            "silo continuous / dual gateway / 14B swap not auto-started; "
            "orch RED alone does not mean router RED (see router_color)"
        ),
        "hints": [
            'Issues -> python propose_recovery.py --symptom "..."',
            "Future actions -> conversation_intent_queue.py propose",
            "Voice -> voice_truth_speak.py --from-tool six_numbers|talk_to_jan",
            "Heal 8090 -> python stack_supervisor.py heal --only llama",
            "Fleet refresh -> python stack_snapshot.py --fleet-health",
            "Thrift rollup -> python router_thrift_rollup.py",
            "Local tenant -> python local_tenant_status.py",
            "Demote only -> python fleet_health_tick.py  # never auto-enable",
        ],
    }

    VAULT.mkdir(parents=True, exist_ok=True)
    atomic_write_json(RECEIPT, payload, indent=2)
    atomic_write_json(UNIFIED_COLOR, stack_color, indent=2)
    # Refresh port-plane receipt so consumers of silent-green-pulse-latest.json stop lying
    port_receipt = {
        "ts": utc(),
        "color": pc.get("color"),
        "summary": pc.get("summary"),
        "gateway": {"ok": bool((ports.get("8642") or {}).get("up"))},
        "proxy_8091": {"up": bool((ports.get("8091") or {}).get("up"))},
        "llama_8090": {"up": bool((ports.get("8090") or {}).get("up"))},
        "requires_llama_8090": True,
        "ok_for_silent_green": pc.get("color") == "GREEN",
        "source": "stack_snapshot_live_ports_v1.4",
        "honesty_note": "Port-plane receipt refreshed by stack_snapshot (W3-P1 2026-07-21)",
        "router_color": router_color,
        "unified_overall": overall,
        "fleet_summary": fc.get("summary"),
        "circuit_summary": circ.get("summary"),
    }
    atomic_write_json(VAULT / "silent-green-pulse-latest.json", port_receipt, indent=2)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(f"stack_snapshot {payload['ts']}")
        for k, v in ports.items():
            print(f"  :{k} up={v.get('up')}")
        print(
            f"  writers cont={writers['continuous']} orch={writers['orchestrator']} "
            f"focus={writers['focus']} drain={writers['drain']}"
        )
        print(
            f"  gateway_run={writers['gateway_run']} service={writers['gateway_service']} meta={writers['meta']}"
        )
        print(f"  green={payload['silent_green']}")
        print(
            f"  router_color={router_color} overall={overall} ports={pc.get('color')} "
            f"orch={oc.get('color')} fleet={fc.get('color')} circuit={circ.get('color')} "
            f"({fc.get('summary')})"
        )
        print(
            f"  thrift={thrift.get('color')} {thrift.get('summary')} | "
            f"tenant={tenant.get('color')} can_serve={tenant.get('can_serve')}"
        )
        if six and "registry_total" in six:
            print(
                f"  silo reg={six.get('registry_total')} landed={six.get('status_landed')} "
                f"ocr_open={six.get('ocr_open')}"
            )
        if payload["last_intent"]:
            print(f"  intent={payload['last_intent']}")
        print(f"  receipt={RECEIPT}")
    exit_plane = router_color if args.exit_on == "router" else overall
    return 0 if str(exit_plane).upper() != "RED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
