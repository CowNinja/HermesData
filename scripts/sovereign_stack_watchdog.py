#!/usr/bin/env python3
"""
sovereign_stack_watchdog.py - 60s stack nervous system (lightweight).

Complements model_management_agent.py (heavy inventory/ranking cron).
This watchdog: port matrix, bounded MoE+proxy recovery, telemetry optimize,
memory hydrate, operations feed refresh.

Usage:
  python sovereign_stack_watchdog.py --once
  python sovereign_stack_watchdog.py --interval 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from windows_subprocess import hidden_powershell_args, prefer_pythonw, run_hidden  # noqa: E402
VAULT = Path(r"D:\PhronesisVault")
WATCHDOG_STATE = VAULT / "Operations" / "logs" / "sovereign-watchdog-state.json"
WATCHDOG_LOG = VAULT / "Operations" / "logs" / "sovereign-stack-watchdog.jsonl"
MAINT_SUMMARY_LOG = VAULT / "Operations" / "logs" / "sovereign-maintenance-summary.jsonl"
VRAM_STATE = SCRIPTS.parent / "state" / "vram-priority.json"
MAINT_LOCK = SCRIPTS.parent / "state" / "maintenance-lock.json"
AGENT_LOG = SCRIPTS.parent / "logs" / "agent.log"
ERRORS_LOG = SCRIPTS.parent / "logs" / "errors.log"
SUMMARY_EVERY_TICKS = 10

LOG_PATTERNS: Dict[str, tuple[str, ...]] = {
    "grammar_crash": ("unable to generate parser", "grammar parser"),
    "provider_503": ("dispatch failed", "provider unreachable", '"code": 503'),
    "tool_halt": ("same_tool_failure_halt", "guardrail halted", "infra_failure_halt"),
    "comfy_down": ("comfyui not reachable", "comfy_bootstrap_failed", ":8188"),
    "vram_pressure": ("out of memory", "insufficient vram", "vram free"),
    "path_drift": (r"k:\hermesdata", "path not found: k:"),
    "image_stall": ("stream_request_complete", "tool image_generate"),
}

COMFY_URL = "http://127.0.0.1:8188"
COMFY_OUTPUT = Path(r"D:\ComfyUI\output")
GATEWAY_STATE = SCRIPTS.parent / "gateway_state.json"
IMAGE_TOOL_TIMEOUT_SEC = 45
IMAGE_TOOL_MAX_RETRIES = 2
IDENTICAL_IMAGE_TOOL_WINDOW_SEC = 30

# Model management agent runs on slower cadence (dashboard refresh / cron)
MGMT_AGENT = SCRIPTS / "model_management_agent.py"
MGMT_INTERVAL_SEC = 3600


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: Dict[str, Any]) -> None:
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def _load_state() -> Dict[str, Any]:
    if WATCHDOG_STATE.is_file():
        try:
            return json.loads(WATCHDOG_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ticks": 0, "last_mgmt_tick": 0.0}


def _save_state(state: Dict[str, Any]) -> None:
    WATCHDOG_STATE.parent.mkdir(parents=True, exist_ok=True)
    WATCHDOG_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def comfy_health_ping(timeout: float = 3.0) -> Dict[str, Any]:
    """Ping Comfy :8188 /system_stats and /queue before image_generate paths."""
    import urllib.error
    import urllib.request

    result: Dict[str, Any] = {
        "ok": False,
        "url": COMFY_URL,
        "system_stats": False,
        "queue_depth": None,
        "queue_running": 0,
    }
    try:
        with urllib.request.urlopen(f"{COMFY_URL.rstrip('/')}/system_stats", timeout=timeout) as resp:
            result["system_stats"] = resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        result["error"] = str(exc)
        return result
    try:
        with urllib.request.urlopen(f"{COMFY_URL.rstrip('/')}/queue", timeout=timeout) as resp:
            if resp.status == 200:
                import json as _json

                q = _json.loads(resp.read().decode("utf-8"))
                pending = q.get("queue_pending") or []
                running = q.get("queue_running") or []
                result["queue_running"] = len(running)
                result["queue_depth"] = len(pending) + len(running)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        result["queue_error"] = str(exc)
    result["ok"] = bool(result["system_stats"])
    return result


def _newest_comfy_png() -> Optional[Dict[str, Any]]:
    if not COMFY_OUTPUT.is_dir():
        return None
    newest: Optional[Path] = None
    newest_mtime = 0.0
    for p in COMFY_OUTPUT.glob("*.png"):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt > newest_mtime:
            newest_mtime = mt
            newest = p
    if not newest:
        return None
    st = newest.stat()
    return {
        "path": str(newest),
        "name": newest.name,
        "mtime": newest_mtime,
        "size": st.st_size,
    }


def poll_comfy_output(state: Dict[str, Any]) -> Dict[str, Any]:
    """Detect new files in D:\\ComfyUI\\output as render-completion fallback."""
    current = _newest_comfy_png()
    prev = state.get("comfy_output_baseline")
    payload: Dict[str, Any] = {"current": current, "new_file": False, "delta_sec": None}
    if current and prev:
        if current.get("name") != prev.get("name") or current.get("mtime", 0) > prev.get("mtime", 0):
            payload["new_file"] = True
            payload["delta_sec"] = round(current["mtime"] - prev.get("mtime", current["mtime"]), 1)
    state["comfy_output_baseline"] = current
    return payload


def detect_stalled_image_turn(state: Dict[str, Any]) -> Dict[str, Any]:
    """Flag Discord turns with image_generate tool_calls but no executor log."""
    import re

    lock = _maintenance_lock_active()
    thread_id = str(lock.get("thread_id") or "")
    stall: Dict[str, Any] = {
        "stalled": False,
        "thread_id": thread_id or None,
        "active_agents": None,
        "last_stream_at": None,
        "last_tool_executor_at": None,
        "comfy_activity": False,
    }
    if GATEWAY_STATE.is_file():
        try:
            gw = json.loads(GATEWAY_STATE.read_text(encoding="utf-8"))
            stall["active_agents"] = int(gw.get("active_agents") or 0)
        except Exception:
            pass
    lines = _tail_lines(AGENT_LOG, 250)
    stream_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO .*stream_request_complete")
    tool_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO .*tool_executor: tool image_generate")
    last_stream = None
    last_tool = None
    for line in reversed(lines):
        if thread_id and thread_id not in line and "image_generate" not in line and "stream_request_complete" not in line:
            continue
        m = stream_re.search(line)
        if m and last_stream is None:
            last_stream = m.group(1)
        m = tool_re.search(line)
        if m and last_tool is None:
            last_tool = m.group(1)
        if last_stream and last_tool:
            break
    stall["last_stream_at"] = last_stream
    stall["last_tool_executor_at"] = last_tool
    comfy = comfy_health_ping(timeout=2.0)
    stall["comfy_activity"] = bool(comfy.get("queue_running")) or bool(comfy.get("queue_depth"))
    if stall["active_agents"] and last_stream and (not last_tool or last_stream > last_tool):
        from datetime import datetime

        try:
            stream_dt = datetime.strptime(last_stream, "%Y-%m-%d %H:%M:%S")
            age_sec = (datetime.now() - stream_dt).total_seconds()
            stall["age_sec"] = round(age_sec, 1)
            if age_sec >= IMAGE_TOOL_TIMEOUT_SEC and not stall["comfy_activity"]:
                stall["stalled"] = True
        except ValueError:
            pass
    retries = int(state.get("image_stall_retries") or 0)
    stall["retries"] = retries
    return stall


def detect_identical_image_tool_loop(state: Dict[str, Any]) -> Dict[str, Any]:
    """Flag rapid duplicate image_generate tool_calls (retry-after-success pattern)."""
    import re
    from datetime import datetime

    sig_re = re.compile(
        r"image_generate.*\"prompt\":\s*\"((?:\\.|[^\"])*)\"",
        re.IGNORECASE,
    )
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+")
    calls: list[tuple[datetime, str]] = []
    for line in _tail_lines(AGENT_LOG, 400):
        if "image_generate" not in line:
            continue
        if "tool_executor: tool image_generate" not in line and "stream_request_complete" not in line:
            continue
        tm = ts_re.search(line)
        sm = sig_re.search(line)
        if not tm:
            continue
        try:
            ts = datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        prompt = (sm.group(1) if sm else line[-120:]).strip()
        calls.append((ts, prompt))

    dupes: list[Dict[str, Any]] = []
    for i in range(1, len(calls)):
        prev_ts, prev_prompt = calls[i - 1]
        cur_ts, cur_prompt = calls[i]
        if prev_prompt != cur_prompt:
            continue
        delta = (cur_ts - prev_ts).total_seconds()
        if 0 <= delta <= IDENTICAL_IMAGE_TOOL_WINDOW_SEC:
            dupes.append(
                {
                    "prompt_tail": prev_prompt[-80:],
                    "delta_sec": round(delta, 1),
                }
            )

    payload: Dict[str, Any] = {
        "detected": bool(dupes),
        "duplicates": dupes[-3:],
        "active_agents": None,
    }
    if GATEWAY_STATE.is_file():
        try:
            gw = json.loads(GATEWAY_STATE.read_text(encoding="utf-8"))
            payload["active_agents"] = int(gw.get("active_agents") or 0)
        except Exception:
            pass
    if dupes and payload.get("active_agents"):
        retries = int(state.get("identical_image_loop_notices") or 0)
        payload["notices"] = retries
        if retries < 2:
            state["identical_image_loop_notices"] = retries + 1
            payload["notify"] = (
                "Detected duplicate image_generate calls within "
                f"{IDENTICAL_IMAGE_TOOL_WINDOW_SEC}s — use /reset if the turn stalls "
                "after Comfy already wrote a PNG."
            )
    else:
        state["identical_image_loop_notices"] = 0
    return payload


def force_deliver_pending_comfy_png(state: Dict[str, Any], comfy_output: Dict[str, Any]) -> Dict[str, Any]:
    """If Comfy wrote a new PNG but Discord turn is still active, force-post it."""
    if not comfy_output.get("new_file"):
        return {"action": "none"}
    lock = _maintenance_lock_active()
    thread_id = str(lock.get("thread_id") or "1521146755985576116")
    active = 0
    if GATEWAY_STATE.is_file():
        try:
            active = int(json.loads(GATEWAY_STATE.read_text(encoding="utf-8")).get("active_agents") or 0)
        except Exception:
            pass
    if not active:
        return {"action": "none", "reason": "no_active_agents"}
    delivered = str(state.get("last_force_delivered_png") or "")
    current = ((comfy_output.get("current") or {}).get("name")) or ""
    if not current or current == delivered:
        return {"action": "none", "reason": "already_delivered"}
    script = SCRIPTS / "ops" / "force_deliver_last_comfy_png.py"
    if not script.is_file():
        return {"action": "missing_script"}
    try:
        proc = run_hidden(
            [sys.executable, str(script), thread_id],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        ok = proc.returncode == 0
        if ok:
            state["last_force_delivered_png"] = current
        return {
            "action": "force_deliver",
            "ok": ok,
            "png": current,
            "stdout": (proc.stdout or "")[-300:],
            "stderr": (proc.stderr or "")[-200:],
        }
    except Exception as exc:
        return {"action": "force_deliver", "ok": False, "error": str(exc)}


def _image_pipeline_paused() -> bool:
    try:
        pause_path = SCRIPTS.parent / "state" / "image-pipeline-pause.json"
        if not pause_path.is_file():
            return False
        data = json.loads(pause_path.read_text(encoding="utf-8"))
        return bool((data or {}).get("paused"))
    except Exception:
        return False


def recover_stalled_image_turn(state: Dict[str, Any], stall: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded recovery: ping Comfy, bootstrap if down, retry up to 2 times."""
    if _image_pipeline_paused():
        return {"action": "skipped", "reason": "image_pipeline_paused"}
    if not stall.get("stalled"):
        return {"action": "none"}
    retries = int(state.get("image_stall_retries") or 0)
    if retries >= IMAGE_TOOL_MAX_RETRIES:
        return {"action": "exhausted", "retries": retries}
    actions: list[Dict[str, Any]] = []
    comfy = comfy_health_ping()
    actions.append({"action": "comfy_health_ping", **comfy})
    if not comfy.get("ok"):
        stack_ps1 = Path(r"D:\ComfyUI\Comfy-Stack.ps1")
        yield_ps1 = SCRIPTS / "Phronesis-Yield-VRAM-For-Image.ps1"
        try:
            if yield_ps1.is_file():
                run_hidden(
                    hidden_powershell_args(str(yield_ps1), "-Quiet"),
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
            if stack_ps1.is_file():
                proc = run_hidden(
                    hidden_powershell_args(str(stack_ps1), "start", "inference"),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                actions.append(
                    {
                        "action": "bootstrap_comfy",
                        "ok": _port_open(8188),
                        "exit_code": proc.returncode,
                        "stdout_tail": (proc.stdout or "")[-200:],
                    }
                )
        except Exception as exc:
            actions.append({"action": "bootstrap_comfy", "ok": False, "error": str(exc)})
    state["image_stall_retries"] = retries + 1
    return {"action": "recover_attempt", "retries": state["image_stall_retries"], "actions": actions}


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _tail_lines(path: Path, max_lines: int = 400) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def scan_log_patterns() -> Dict[str, Any]:
    """Scan recent agent/errors logs for recurring sovereign failure signatures."""
    hits: Dict[str, int] = {k: 0 for k in LOG_PATTERNS}
    samples: Dict[str, str] = {}
    for path in (AGENT_LOG, ERRORS_LOG):
        for line in _tail_lines(path, 500):
            lower = line.lower()
            for key, markers in LOG_PATTERNS.items():
                if any(m in lower for m in markers):
                    hits[key] += 1
                    if key not in samples:
                        samples[key] = line[-240:]
    active = [k for k, n in hits.items() if n > 0]
    return {"hits": hits, "active_patterns": active, "samples": samples}


def _load_vram_mode() -> str:
    if not VRAM_STATE.is_file():
        return "unknown"
    try:
        raw = json.loads(VRAM_STATE.read_text(encoding="utf-8"))
        return str(raw.get("mode") or "unknown")
    except Exception:
        return "unknown"


def _maintenance_lock_active() -> Dict[str, Any]:
    if not MAINT_LOCK.is_file():
        return {"active": False}
    try:
        raw = json.loads(MAINT_LOCK.read_text(encoding="utf-8"))
        until = raw.get("until")
        if until:
            from datetime import datetime

            if datetime.now().astimezone() > datetime.fromisoformat(str(until)):
                return {"active": False}
        return {"active": True, **raw}
    except Exception:
        return {"active": False}


def vram_mode_recovery() -> Dict[str, Any]:
    """Align llama/Comfy with vram-priority.json (text vs image)."""
    lock = _maintenance_lock_active()
    if lock.get("active") and lock.get("protect_vram"):
        return {"vram_mode": _load_vram_mode(), "skipped": True, "reason": lock.get("reason")}

    mode = _load_vram_mode()
    actions: list[Dict[str, Any]] = []
    yield_text = SCRIPTS / "Phronesis-Yield-VRAM-For-Text.ps1"
    comfy_stack = Path(r"D:\ComfyUI\Comfy-Stack.ps1")

    if mode == "text" and _port_open(8188):
        try:
            proc = run_hidden(
                hidden_powershell_args(str(SCRIPTS / "Phronesis-Yield-VRAM-For-Text.ps1"), "-Quiet"),
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(SCRIPTS),
            )
            actions.append(
                {
                    "action": "yield_comfy_text_mode",
                    "ok": not _port_open(8188),
                    "exit_code": proc.returncode,
                }
            )
        except Exception as exc:
            actions.append({"action": "yield_comfy_text_mode", "ok": False, "error": str(exc)})

    if mode == "text" and not _port_open(8090):
        try:
            proc = run_hidden(
                hidden_powershell_args(str(yield_text), "-StartLlama", "-Quiet"),
                capture_output=True,
                text=True,
                timeout=200,
                cwd=str(SCRIPTS),
            )
            actions.append(
                {
                    "action": "start_llama_text_mode",
                    "ok": _port_open(8090),
                    "exit_code": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-300:],
                }
            )
        except Exception as exc:
            actions.append({"action": "start_llama_text_mode", "ok": False, "error": str(exc)})

    pipeline_paused = False
    try:
        pause_path = Path(r"D:\HermesData\state\image-pipeline-pause.json")
        if pause_path.is_file():
            import json as _json

            pipeline_paused = bool((_json.loads(pause_path.read_text(encoding="utf-8")) or {}).get("paused"))
    except Exception:
        pipeline_paused = False

    if pipeline_paused and _port_open(8188) and comfy_stack.is_file():
        try:
            proc = run_hidden(
                hidden_powershell_args(str(comfy_stack), "stop", "inference"),
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(comfy_stack.parent),
            )
            actions.append(
                {
                    "action": "stop_comfy_pipeline_paused",
                    "ok": not _port_open(8188),
                    "exit_code": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-300:],
                }
            )
        except Exception as exc:
            actions.append({"action": "stop_comfy_pipeline_paused", "ok": False, "error": str(exc)})

    if mode == "image" and not pipeline_paused and not _port_open(8188) and comfy_stack.is_file():
        try:
            proc = run_hidden(
                hidden_powershell_args(str(comfy_stack), "start", "inference"),
                capture_output=True,
                text=True,
                timeout=240,
                cwd=str(comfy_stack.parent),
            )
            actions.append(
                {
                    "action": "start_comfy_image_mode",
                    "ok": _port_open(8188),
                    "exit_code": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-300:],
                }
            )
        except Exception as exc:
            actions.append({"action": "start_comfy_image_mode", "ok": False, "error": str(exc)})

    both_up = _port_open(8090) and _port_open(8188)
    return {
        "vram_mode": mode,
        "actions": actions,
        "dual_stack": both_up,
        "ports": {"8090": _port_open(8090), "8091": _port_open(8091), "8188": _port_open(8188), "8642": _port_open(8642)},
    }


def write_maintenance_summary(state: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "event": "maintenance_summary",
        "tick": state.get("ticks"),
        "status": (payload.get("matrix") or {}).get("status"),
        "vram_mode": payload.get("vram_recovery", {}).get("vram_mode"),
        "dual_stack": payload.get("vram_recovery", {}).get("dual_stack"),
        "log_patterns": payload.get("log_scan", {}).get("active_patterns"),
        "recoveries": (payload.get("preflight") or {}).get("recoveries"),
        "fixes_applied": payload.get("vram_recovery", {}).get("actions"),
    }
    try:
        MAINT_SUMMARY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(MAINT_SUMMARY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **summary}) + "\n")
    except Exception:
        pass
    state["last_summary"] = summary
    state["last_summary_at"] = _utc_now()
    return summary


def memory_hydrate_tick() -> Dict[str, Any]:
    """Boot-hydrate sovereign memory for gateway continuity."""
    try:
        from sovereign_memory_manager import hydrate_boot_state  # type: ignore

        payload = hydrate_boot_state(platform="hermes")
        return {"ok": True, "event": "memory_hydrate", "hydrated": bool(payload)}
    except Exception as exc:
        return {"ok": False, "event": "memory_hydrate", "error": str(exc)}


def run_tick(*, auto_recover: bool = True, run_mgmt: bool = False, once: bool = False) -> Dict[str, Any]:
    """Single watchdog cycle."""
    sys.path.insert(0, str(SCRIPTS))
    from model_resource_manager import preflight_for_agent, tier_matrix, append_watchdog_log  # type: ignore
    from sovereign_telemetry_monitor import get_telemetry_monitor  # type: ignore
    from autonomous_operations_feed import refresh_panel  # type: ignore

    state = _load_state()
    state["ticks"] = int(state.get("ticks") or 0) + 1

    log_scan = scan_log_patterns()
    vram_recovery = vram_mode_recovery() if auto_recover else {"vram_mode": _load_vram_mode(), "skipped": True}

    comfy_health = comfy_health_ping()
    comfy_output = poll_comfy_output(state)
    image_stall = detect_stalled_image_turn(state)
    image_tool_loop = detect_identical_image_tool_loop(state)
    image_recovery = (
        recover_stalled_image_turn(state, image_stall)
        if auto_recover and image_stall.get("stalled")
        else {"action": "none"}
    )
    force_delivery = (
        force_deliver_pending_comfy_png(state, comfy_output)
        if auto_recover
        else {"action": "none"}
    )

    preflight = preflight_for_agent(auto_recover=auto_recover)
    matrix = preflight.get("matrix") or tier_matrix(force_refresh=True)
    telemetry_optimize = get_telemetry_monitor().optimize_tick()
    hydrate = memory_hydrate_tick()
    ops_feed = refresh_panel()

    mgmt_result: Optional[Dict[str, Any]] = None
    now = time.time()
    last_mgmt = float(state.get("last_mgmt_tick") or 0.0)
    should_mgmt = run_mgmt or (not once and (now - last_mgmt) >= MGMT_INTERVAL_SEC)
    if should_mgmt:
        try:
            py = SCRIPTS.parent / "hermes-agent" / "venv" / "Scripts" / "python.exe"
            if not py.is_file():
                py = Path(sys.executable)
            proc = run_hidden(
                [str(py), str(MGMT_AGENT), "--tick"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(SCRIPTS),
            )
            parsed: Dict[str, Any] = {}
            if proc.stdout.strip():
                try:
                    parsed = json.loads(proc.stdout)
                except Exception:
                    parsed = {"raw": proc.stdout[-600:]}
            mgmt_result = {"ok": proc.returncode == 0, **parsed}
            state["last_mgmt_tick"] = now
        except Exception as exc:
            mgmt_result = {"ok": False, "error": str(exc)}

    tick_payload = {
        "event": "watchdog_tick",
        "tick_number": state["ticks"],
        "preflight": {
            "ok": preflight.get("ok"),
            "recovered": preflight.get("recovered"),
            "recoveries": preflight.get("recoveries"),
        },
        "log_scan": log_scan,
        "vram_recovery": vram_recovery,
        "comfy_health": comfy_health,
        "comfy_output_poll": comfy_output,
        "image_turn_stall": image_stall,
        "image_tool_loop": image_tool_loop,
        "image_turn_recovery": image_recovery,
        "image_force_delivery": force_delivery,
        "telemetry_optimize": telemetry_optimize,
        "memory_hydrate": hydrate,
        "operations_feed": {"ok": True, "status": ops_feed.get("status")},
        "model_management": mgmt_result,
    }

    append_watchdog_log(tick_payload)
    _log(tick_payload)

    state["last_status"] = matrix.get("status")
    state["last_tick_at"] = _utc_now()
    state["last_matrix"] = matrix
    summary = None
    if state["ticks"] % SUMMARY_EVERY_TICKS == 0:
        summary = write_maintenance_summary(state, tick_payload)
    _save_state(state)

    return {
        "tick": tick_payload,
        "matrix": matrix,
        "operations_panel": ops_feed,
        "maintenance_summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sovereign stack watchdog")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit")
    parser.add_argument("--interval", type=int, default=60, help="Daemon interval seconds")
    parser.add_argument("--no-recover", action="store_true", help="Probe only, no auto-recover")
    parser.add_argument("--with-mgmt", action="store_true", help="Force model_management_agent tick")
    args = parser.parse_args()

    auto_recover = not args.no_recover

    if args.once:
        result = run_tick(auto_recover=auto_recover, run_mgmt=args.with_mgmt, once=True)
        print(json.dumps(result, indent=2))
        status = (result.get("matrix") or {}).get("status")
        return 0 if status in ("GREEN", "YELLOW") else 1

    while True:
        try:
            run_tick(auto_recover=auto_recover, run_mgmt=args.with_mgmt, once=False)
        except Exception as exc:
            _log({"event": "watchdog_error", "error": str(exc)})
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())