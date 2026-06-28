#!/usr/bin/env python3
"""
lru_router_manager.py — Fuzzy context-aware LRU coordination for port 8090.

Phronesis MoE unified router: preload hints, activity pinning, idle-aware eviction.
Designed for 128GB RAM — tend toward keeping models warm during active work,
soft unload only when idle and memory pressure warrants it.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

UNIFIED_PORT = 8090
STATE_PATH = Path(r"D:\PhronesisVault\Operations\logs\lru-router-state.json")
ACTIVITY_LOG = Path(r"D:\PhronesisVault\Operations\logs\lru-router-activity.jsonl")
PIN_CONFIG_PATH = Path(r"D:\PhronesisVault\Operations\lru-pinned-models-v0.1.json")
PIN_TELEMETRY_LOG = Path(r"D:\PhronesisVault\Operations\logs\vram-pin-telemetry.jsonl")

_DEFAULT_PINNED = ("qwen2-5-7b",)
_KEEPALIVE_THREAD: Optional[threading.Thread] = None
_KEEPALIVE_STOP = threading.Event()

# Legacy dotted aliases from early pivot configs → models.ini section ids (hyphens)
_LOGICAL_MODEL_ALIASES: Dict[str, str] = {
    "llama-3.1-8b-abliterated": "qwen2-5-7b",
    "llama-3.1-8b": "llama-3-1-8b",
    "qwen2.5-coder-14b-abliterated": "qwen2-5-7b",
}

# Tier → preset logical model id (models.ini sections)
_UNIFIED_LOGICAL = "qwen2-5-7b"
MODELS_INI_PATH = Path(r"D:\PhronesisModels\presets\models.ini")
UNIFIED_GPU_NGL = 99
UNIFIED_CTX_SIZE = 12288


def normalize_logical_model_id(model_id: str) -> str:
    """Map legacy dotted logical ids to models.ini section names."""
    mid = str(model_id or "").strip()
    return _LOGICAL_MODEL_ALIASES.get(mid, mid)

TIER_LOGICAL_MODELS: Dict[str, str] = {
    "local_hot": _UNIFIED_LOGICAL,
    "local_warm": _UNIFIED_LOGICAL,
    "local_classifier": _UNIFIED_LOGICAL,
    "local_cold": _UNIFIED_LOGICAL,
    "local_roleplay": _UNIFIED_LOGICAL,
    "local_generalist": _UNIFIED_LOGICAL,
}

# Single-model pivot — no neighbor preloads
TIER_PRELOAD_NEIGHBORS: Dict[str, List[str]] = {}

# Fuzzy thresholds (seconds)
ACTIVE_SESSION_SEC = 900       # 15 min since last dispatch = active project
DEEP_IDLE_SEC = 3600           # 1 hr = allow softer eviction profile
GATEWAY_ACTIVE_PORTS = (8642, 3001)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def unified_router_up() -> bool:
    return _port_open(UNIFIED_PORT)


def load_pin_config() -> Dict[str, Any]:
    """Pinned-model policy for always-on roleplay + hot tier."""
    defaults: Dict[str, Any] = {
        "vram_gb": 12,
        "pinned_logical_models": list(_DEFAULT_PINNED),
        "generalist_logical": _UNIFIED_LOGICAL,
        "models_max_floor": 1,
        "ctx_size_default": UNIFIED_CTX_SIZE,
        "gpu_ngl_default": UNIFIED_GPU_NGL,
        "keepalive_interval_sec": 300,
    }
    if PIN_CONFIG_PATH.is_file():
        try:
            data = json.loads(PIN_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**defaults, **data}
        except Exception:
            pass
    return defaults


def get_pinned_logical_models() -> List[str]:
    cfg = load_pin_config()
    raw = cfg.get("pinned_logical_models") or list(_DEFAULT_PINNED)
    out: List[str] = []
    seen: Set[str] = set()
    for item in raw:
        mid = normalize_logical_model_id(str(item or "").strip())
        if mid and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def recommended_ctx_size(explicit: Optional[int] = None) -> int:
    """Ctx budget that keeps dual-pin (7B + Rocinante) inside 12GB VRAM."""
    if explicit is not None and explicit > 0:
        return int(explicit)
    env_val = os.environ.get("PHRONESIS_CTX_SIZE")
    if env_val:
        try:
            return max(2048, int(env_val))
        except ValueError:
            pass
    cfg = load_pin_config()
    pinned = get_pinned_logical_models()
    vram_gb = int(cfg.get("vram_gb") or 12)
    if len(pinned) >= 2 and vram_gb <= 12:
        return int(cfg.get("ctx_size_12gb_dual") or 12288)
    return int(cfg.get("ctx_size_default") or UNIFIED_CTX_SIZE)


def ensure_unified_generalist_gpu_preset() -> Dict[str, Any]:
    """Patch models.ini so unified 14B uses max GPU offload with balanced ctx on 12GB VRAM."""
    cfg = load_pin_config()
    logical = normalize_logical_model_id(str(cfg.get("generalist_logical") or _UNIFIED_LOGICAL))
    ngl = int(cfg.get("gpu_ngl_default") or UNIFIED_GPU_NGL)
    ctx = int(cfg.get("ctx_size_default") or UNIFIED_CTX_SIZE)
    if not MODELS_INI_PATH.is_file():
        return {"ok": False, "reason": "models_ini_missing"}

    lines = MODELS_INI_PATH.read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    in_section = False
    seen_ngl = False
    seen_ctx = False
    seen_parallel = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section:
                if not seen_ngl:
                    out.append(f"ngl = {ngl}")
                if not seen_ctx:
                    out.append(f"ctx-size = {ctx}")
                if not seen_parallel:
                    out.append("parallel = 1")
            in_section = stripped == f"[{logical}]"
            seen_ngl = seen_ctx = seen_parallel = False
            out.append(line)
            continue
        if in_section:
            key = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else ""
            if key == "ngl":
                out.append(f"ngl = {ngl}")
                seen_ngl = True
                continue
            if key == "ctx-size":
                out.append(f"ctx-size = {ctx}")
                seen_ctx = True
                continue
            if key == "parallel":
                out.append("parallel = 1")
                seen_parallel = True
                continue
        out.append(line)
    if in_section:
        if not seen_ngl:
            out.append(f"ngl = {ngl}")
        if not seen_ctx:
            out.append(f"ctx-size = {ctx}")
        if not seen_parallel:
            out.append("parallel = 1")
    MODELS_INI_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"ok": True, "logical": logical, "ngl": ngl, "ctx_size": ctx, "parallel": 1}


def _load_state() -> Dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "last_dispatch": None,
        "last_preload": {},
        "pinned_logical": [],
        "session_active": False,
    }


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _log_event(event: Dict[str, Any]) -> None:
    try:
        ACTIVITY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _utc_now(), **event}) + "\n")
    except Exception:
        pass


def seconds_since_last_dispatch() -> float:
    state = _load_state()
    ts = state.get("last_dispatch")
    if not ts:
        return 1e9
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - then).total_seconds()
    except Exception:
        return 1e9


def gateway_or_workspace_active() -> bool:
    return any(_port_open(p) for p in GATEWAY_ACTIVE_PORTS)


def activity_profile() -> str:
    """
    Fuzzy activity bucket:
      active_project — recent dispatches or gateway up
      idle_soft      — no dispatch 15–60 min
      deep_idle      — no dispatch > 1 hr and no gateway
    """
    since = seconds_since_last_dispatch()
    if since < ACTIVE_SESSION_SEC or gateway_or_workspace_active():
        return "active_project"
    if since < DEEP_IDLE_SEC:
        return "idle_soft"
    return "deep_idle"


def recommended_models_max() -> int:
    """LRU slot count — pinned models are never evicted below models_max_floor."""
    cfg = load_pin_config()
    pinned = get_pinned_logical_models()
    floor = max(int(cfg.get("models_max_floor") or 2), len(pinned) or 1)

    explicit = os.environ.get("PHRONESIS_MODELS_MAX")
    if explicit:
        try:
            return max(floor, int(explicit))
        except ValueError:
            pass

    # Dual-pin on 12GB: cap at floor so a third model cannot evict residents.
    vram_gb = int(cfg.get("vram_gb") or 12)
    if pinned and vram_gb <= 12:
        return floor

    profile = activity_profile()
    if profile == "active_project":
        return max(floor, 4)
    if profile == "idle_soft":
        return max(floor, 3)
    return max(floor, 2)


def recommended_sleep_idle_seconds() -> int:
    """llama-server --sleep-idle-seconds — long during projects, shorter when away."""
    profile = activity_profile()
    if profile == "active_project":
        return 0  # disable aggressive idle unload mid-project
    if profile == "idle_soft":
        return 1800
    return 600


def logical_model_for_tier(tier: str) -> str:
    return normalize_logical_model_id(
        TIER_LOGICAL_MODELS.get(tier, TIER_LOGICAL_MODELS["local_hot"])
    )


def list_loaded_models(port: int = UNIFIED_PORT) -> List[str]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data") or data.get("models") or []
        ids: List[str] = []
        for m in models:
            if isinstance(m, dict):
                mid = m.get("id") or m.get("model") or m.get("name")
                if mid:
                    ids.append(str(mid))
            else:
                ids.append(str(m))
        return ids
    except Exception:
        return []


def record_dispatch(tier: str, logical_model: Optional[str] = None, task_type: Optional[str] = None) -> None:
    state = _load_state()
    state["last_dispatch"] = _utc_now()
    state["last_tier"] = tier
    state["last_logical_model"] = normalize_logical_model_id(
        logical_model or logical_model_for_tier(tier)
    )
    state["last_task_type"] = task_type
    state["session_active"] = True
    state["activity_profile"] = activity_profile()
    _save_state(state)
    _log_event({"event": "dispatch", "tier": tier, "logical_model": state["last_logical_model"]})


def preload_candidates_for_route(route_preview: Dict[str, Any]) -> List[str]:
    """Build preemptive preload set from tier-preview + recent activity."""
    tier = str(route_preview.get("tier") or "local_hot")
    primary = normalize_logical_model_id(
        route_preview.get("logical_model") or logical_model_for_tier(tier)
    )
    candidates: List[str] = list(get_pinned_logical_models())
    candidates.append(str(primary))
    neighbors = TIER_PRELOAD_NEIGHBORS.get(tier, [])
    candidates.extend(neighbors)
    # Mid-project: keep last-used tier warm too
    state = _load_state()
    last = state.get("last_logical_model")
    if last and last not in candidates:
        candidates.append(str(last))
    # Active session: always keep hot coder resident
    if activity_profile() == "active_project":
        hot = TIER_LOGICAL_MODELS["local_hot"]
        if hot not in candidates:
            candidates.append(hot)
    seen: Set[str] = set()
    out: List[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _preload_one(logical_model: str, port: int = UNIFIED_PORT) -> Dict[str, Any]:
    logical_model = normalize_logical_model_id(logical_model)
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    payload = {
        "model": logical_model,
        "messages": [{"role": "user", "content": "."}],
        "max_tokens": 1,
        "temperature": 0.0,
        "stream": False,
    }
    started = time.time()
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        elapsed = round(time.time() - started, 2)
        return {"ok": True, "logical_model": logical_model, "elapsed_sec": elapsed}
    except Exception as exc:
        return {"ok": False, "logical_model": logical_model, "error": str(exc)}


def send_preload_hints(
    logical_models: List[str],
    *,
    async_mode: bool = True,
    port: int = UNIFIED_PORT,
) -> Dict[str, Any]:
    """Warm LRU slots before main dispatch — reduces swap TTFT."""
    if not unified_router_up():
        return {"ok": False, "reason": "8090_down", "hints": []}

    pinned = get_pinned_logical_models()
    merged: List[str] = []
    seen: Set[str] = set()
    for mid in list(pinned) + list(logical_models or []):
        norm = normalize_logical_model_id(mid)
        if norm and norm not in seen:
            seen.add(norm)
            merged.append(norm)

    loaded = set(list_loaded_models(port))
    to_warm = [m for m in merged if m not in loaded]
    if not to_warm:
        return {"ok": True, "skipped": True, "reason": "already_loaded", "loaded": list(loaded)}

    state = _load_state()
    results: List[Dict[str, Any]] = []

    def _run() -> None:
        for mid in to_warm:
            r = _preload_one(mid, port)
            results.append(r)
            state.setdefault("last_preload", {})[mid] = _utc_now()
        state["pinned_logical"] = list(
            set((state.get("pinned_logical") or []) + pinned + to_warm)
        )
        _save_state(state)
        _log_event({"event": "preload", "models": to_warm, "pinned": pinned, "results": results})
        _log_pin_telemetry("preload_complete", {"warmed": to_warm, "results": results})

    if async_mode:
        threading.Thread(target=_run, daemon=True, name=f"preload-8090-{len(to_warm)}").start()
        return {"ok": True, "async": True, "warming": to_warm, "already_loaded": list(loaded)}

    for mid in to_warm:
        results.append(_preload_one(mid, port))
    return {"ok": True, "async": False, "results": results}


def preload_from_route_preview(route_preview: Dict[str, Any]) -> Dict[str, Any]:
    models = preload_candidates_for_route(route_preview)
    return send_preload_hints(models, async_mode=True)


def _log_pin_telemetry(event: str, extra: Optional[Dict[str, Any]] = None) -> None:
    try:
        tel = vram_pin_telemetry()
        tel["event"] = event
        if extra:
            tel.update(extra)
        PIN_TELEMETRY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PIN_TELEMETRY_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(tel, ensure_ascii=False) + "\n")
    except Exception:
        pass


def vram_pin_telemetry(port: int = UNIFIED_PORT) -> Dict[str, Any]:
    """Verification telemetry for always-on Rocinante + hot tier."""
    cfg = load_pin_config()
    pinned = get_pinned_logical_models()
    loaded = list_loaded_models(port) if unified_router_up() else []
    loaded_set = set(loaded)
    missing = [m for m in pinned if m not in loaded_set]
    return {
        "timestamp": _utc_now(),
        "unified_up": unified_router_up(),
        "vram_gb": cfg.get("vram_gb"),
        "pinned_logical_models": pinned,
        "hot_tier_logical": cfg.get("hot_tier_logical"),
        "roleplay_logical": cfg.get("roleplay_logical"),
        "models_max_recommended": recommended_models_max(),
        "ctx_size_recommended": recommended_ctx_size(),
        "loaded_models": loaded,
        "pinned_resident": [m for m in pinned if m in loaded_set],
        "pinned_missing": missing,
        "all_pinned_resident": len(missing) == 0 and bool(pinned),
        "activity_profile": activity_profile(),
        "sleep_idle_recommended": recommended_sleep_idle_seconds(),
    }


def pin_startup_warm(*, port: int = UNIFIED_PORT, async_mode: bool = False) -> Dict[str, Any]:
    """Load all pinned models at router boot — Rocinante always-on."""
    pinned = get_pinned_logical_models()
    if not pinned:
        return {"ok": False, "reason": "no_pinned_models"}
    state = _load_state()
    state["pinned_logical"] = pinned
    state["pin_startup_at"] = _utc_now()
    _save_state(state)
    result = send_preload_hints(pinned, async_mode=async_mode, port=port)
    _log_pin_telemetry("pin_startup", {"result": result})
    return result


def ensure_pinned_resident(*, port: int = UNIFIED_PORT) -> Dict[str, Any]:
    """Re-warm any pinned model that fell out of LRU — idempotent keepalive tick."""
    tel = vram_pin_telemetry(port)
    missing = tel.get("pinned_missing") or []
    if not missing:
        return {"ok": True, "skipped": True, "telemetry": tel}
    result = send_preload_hints(missing, async_mode=False, port=port)
    _log_pin_telemetry("pin_keepalive_rewarm", {"missing": missing, "result": result})
    return {"ok": True, "rewarmed": missing, "result": result, "telemetry": vram_pin_telemetry(port)}


def start_pin_keepalive(*, interval_sec: Optional[int] = None, port: int = UNIFIED_PORT) -> Dict[str, Any]:
    """Background daemon — periodic pinned-model residency checks."""
    global _KEEPALIVE_THREAD
    cfg = load_pin_config()
    interval = int(interval_sec or cfg.get("keepalive_interval_sec") or 300)
    if _KEEPALIVE_THREAD and _KEEPALIVE_THREAD.is_alive():
        return {"ok": True, "already_running": True, "interval_sec": interval}

    _KEEPALIVE_STOP.clear()

    def _loop() -> None:
        while not _KEEPALIVE_STOP.wait(interval):
            try:
                ensure_pinned_resident(port=port)
            except Exception as exc:
                _log_event({"event": "pin_keepalive_error", "error": str(exc)})

    _KEEPALIVE_THREAD = threading.Thread(
        target=_loop,
        daemon=True,
        name="vram-pin-keepalive",
    )
    _KEEPALIVE_THREAD.start()
    _log_pin_telemetry("keepalive_started", {"interval_sec": interval})
    return {"ok": True, "interval_sec": interval}


def stop_pin_keepalive() -> None:
    _KEEPALIVE_STOP.set()


def router_status() -> Dict[str, Any]:
    return {
        "timestamp": _utc_now(),
        "unified_port": UNIFIED_PORT,
        "unified_up": unified_router_up(),
        "activity_profile": activity_profile(),
        "models_max_recommended": recommended_models_max(),
        "ctx_size_recommended": recommended_ctx_size(),
        "sleep_idle_recommended": recommended_sleep_idle_seconds(),
        "loaded_models": list_loaded_models() if unified_router_up() else [],
        "pin_config": load_pin_config(),
        "pin_telemetry": vram_pin_telemetry(),
        "state": _load_state(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phronesis LRU router manager")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--telemetry", action="store_true", help="VRAM pin verification telemetry")
    parser.add_argument("--pin-startup", action="store_true", help="Warm all pinned models (sync)")
    parser.add_argument("--ensure-pinned", action="store_true", help="Re-warm missing pinned models")
    parser.add_argument("--keepalive", action="store_true", help="Start pinned-model keepalive daemon")
    parser.add_argument("--preload", metavar="MODEL", nargs="*", help="Logical model ids to warm")
    parser.add_argument("--tier", help="Preload from tier (local_hot, local_warm, ...)")
    parser.add_argument("--ensure-gpu-preset", action="store_true", help="Patch models.ini GPU offload for unified generalist")
    args = parser.parse_args()

    if args.ensure_gpu_preset:
        print(json.dumps(ensure_unified_generalist_gpu_preset(), indent=2))
    elif args.pin_startup:
        print(json.dumps(pin_startup_warm(async_mode=False), indent=2))
    elif args.ensure_pinned:
        print(json.dumps(ensure_pinned_resident(), indent=2))
    elif args.keepalive:
        print(json.dumps(start_pin_keepalive(), indent=2))
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            stop_pin_keepalive()
    elif args.telemetry:
        print(json.dumps(vram_pin_telemetry(), indent=2))
    elif args.preload:
        print(json.dumps(send_preload_hints(args.preload, async_mode=False), indent=2))
    elif args.tier:
        print(json.dumps(send_preload_hints([logical_model_for_tier(args.tier)], async_mode=False), indent=2))
    else:
        print(json.dumps(router_status(), indent=2))
