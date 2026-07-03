#!/usr/bin/env python3
"""
model_resource_manager.py — MoE tier health, context budgeting, recovery hooks.

Config-driven resource layer for sovereign router. Used by sovereign_openai_proxy
and Run-Phronesis-LocalVerification.ps1 extensions.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VAULT = Path(r"D:\PhronesisVault")
HERMES_SCRIPTS = Path(r"D:\HermesData\scripts")
STATE_PATH = VAULT / "Operations" / "logs" / "model-resource-state.json"
MOE_MAP = VAULT / "Operations" / "MoE-Task-Type-Map-v0.1.json"
START_MOE_PS1 = HERMES_SCRIPTS / "Start-MoE-Stack.ps1"
START_UNIFIED_PS1 = HERMES_SCRIPTS / "Start-Unified-Router-8090.ps1"
START_LLAMA_PS1 = HERMES_SCRIPTS / "ops" / "02-start-llama.ps1"
START_PROXY_PS1 = HERMES_SCRIPTS / "ops" / "03-start-proxy.ps1"
START_PROXY_LEGACY_PS1 = HERMES_SCRIPTS / "Start-Sovereign-Proxy-8091.ps1"
WATCHDOG_LOG = VAULT / "Operations" / "logs" / "sovereign-stack-watchdog.jsonl"
MAX_RECOVERY_ATTEMPTS = 3

DEFAULT_PORTS = {
    "8081": {"tier": "local_hot", "role": "code/daily"},
    "8082": {"tier": "local_warm", "role": "synthesis"},
    "8083": {"tier": "local_classifier", "role": "classify/metadata"},
    "8090": {"tier": "unified_router", "role": "lru_moe_primary"},
    "8091": {"tier": "sovereign_proxy", "role": "hermes_agent_gateway"},
    "11434": {"tier": "ollama", "role": "interim_fallback"},
}

# Context window hints per tier (tokens) — expand via MoE map later
TIER_CONTEXT_BUDGET = {
    "local_classifier": 12288,
    "local_hot": 12288,
    "local_warm": 32768,
    "local_cold": 65536,
    "local_roleplay": 12288,
    "local_generalist": 12288,
    "ollama": 32768,
}

MODELS_8090_INI = VAULT / "Operations" / "models-8090.ini"


def live_llama_ctx_budget() -> int:
    """Read active ctx-size from phronesis-core.json, then models-8090.ini."""
    try:
        core_path = HERMES_SCRIPTS / "phronesis-core.json"
        if core_path.is_file():
            core = json.loads(core_path.read_text(encoding="utf-8"))
            ctx = int(core.get("ctx_size") or 0)
            if ctx >= 2048:
                return ctx
    except Exception:
        pass
    try:
        if MODELS_8090_INI.is_file():
            in_default = False
            for line in MODELS_8090_INI.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    in_default = stripped.lower() == "[default]"
                    continue
                if in_default and stripped.lower().startswith("ctx-size"):
                    val = stripped.split("=", 1)[1].strip()
                    return max(2048, int(val))
    except Exception:
        pass
    return 8192


def completion_reserve_for_ctx(ctx: int) -> int:
    """Leave headroom for completion + tool schemas inside the live llama ctx."""
    return min(4096, max(768, int(ctx) // 4))


def _port_open(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


_MATRIX_CACHE: Optional[Dict[str, Any]] = None
_MATRIX_CACHE_AT: float = 0.0
_MATRIX_TTL_SEC = 1.0


def _ports_to_probe() -> List[int]:
    """Unified mode only needs live router + proxy; skip dead legacy/aux ports."""
    if _unified_mode_enabled():
        return [8090, 8091]
    return [int(p) for p in DEFAULT_PORTS]


def _unified_mode_enabled() -> bool:
    try:
        if MOE_MAP.is_file():
            data = json.loads(MOE_MAP.read_text(encoding="utf-8-sig"))
            return bool((data.get("unified_router") or {}).get("enabled"))
    except Exception:
        pass
    return False


def tier_matrix(*, force_refresh: bool = False) -> Dict[str, Any]:
    global _MATRIX_CACHE, _MATRIX_CACHE_AT
    now = time.time()
    if not force_refresh and _MATRIX_CACHE and (now - _MATRIX_CACHE_AT) < _MATRIX_TTL_SEC:
        return dict(_MATRIX_CACHE)

    probed = {p: _port_open(p) for p in _ports_to_probe()}
    ports = {str(p): probed.get(p, False) for p in DEFAULT_PORTS}
    for p, up in probed.items():
        ports[str(p)] = up
    unified_up = ports.get("8090", False)
    legacy_up = ports.get("8081") and (ports.get("8082") or ports.get("8083"))
    moe_ready = unified_up or legacy_up
    router_mode = "unified_8090" if unified_up and _unified_mode_enabled() else (
        "legacy_808x" if legacy_up else "down"
    )
    proxy_ready = ports.get("8091", False)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ports": ports,
        "router_mode": router_mode,
        "moe_ready": moe_ready,
        "proxy_ready": proxy_ready,
        "agent_local_ready": moe_ready and proxy_ready,
        "status": "GREEN" if moe_ready and proxy_ready else ("YELLOW" if moe_ready else "RED"),
    }
    _MATRIX_CACHE = result
    _MATRIX_CACHE_AT = now
    return result


def context_budget_for_tier(tier: str) -> int:
    live = live_llama_ctx_budget()
    return min(TIER_CONTEXT_BUDGET.get(tier, 12288), live)


# Hermes agent gateway advertises this window; proxy trims to per-tier safe input.
HERMES_AGENT_MIN_CONTEXT = 65536
COMPLETION_RESERVE_TOKENS = 12288
TIER_INPUT_SAFETY_RATIO = 0.85


def input_budget_for_tier(
    tier: str,
    completion_reserve: Optional[int] = None,
    safety_ratio: float = TIER_INPUT_SAFETY_RATIO,
    extra_reserve_tokens: int = 0,
) -> int:
    """Safe prompt token cap for a MoE tier (leaves room for KV cache + completion)."""
    gross = context_budget_for_tier(tier)
    reserve = completion_reserve if completion_reserve is not None else completion_reserve_for_ctx(gross)
    reserve += max(0, int(extra_reserve_tokens))
    return max(1024, int((gross - reserve) * safety_ratio))


def effective_tier_for_trim(planned_tier: str) -> str:
    """Downgrade budget when the planned tier port is down (matches bridge fallback)."""
    matrix = tier_matrix()
    ports = matrix.get("ports") or {}
    if matrix.get("router_mode") == "unified_8090" and ports.get("8090"):
        return planned_tier
    if planned_tier == "local_warm" and not ports.get("8082"):
        return "local_hot"
    if planned_tier == "local_classifier" and not ports.get("8083"):
        return "local_hot"
    if planned_tier == "local_cold" and not ports.get("8082"):
        return "local_hot"
    return planned_tier


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"recovery_attempts": {}, "last_matrix": None}


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _recovery_allowed(state: Dict[str, Any], key: str) -> bool:
    attempts = int(state.get("recovery_attempts", {}).get(key, 0))
    return attempts < MAX_RECOVERY_ATTEMPTS


def reset_recovery_counters_on_green(matrix: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Clear recovery attempt counters when stack is healthy (allows future self-heal)."""
    matrix = matrix or tier_matrix()
    if matrix.get("agent_local_ready"):
        state = load_state()
        prior = dict(state.get("recovery_attempts") or {})
        if prior:
            state["recovery_attempts"] = {}
            state["last_green"] = datetime.now(timezone.utc).isoformat()
            save_state(state)
            return {"reset": True, "prior": prior}
    return {"reset": False}


def attempt_proxy_recovery(dry_run: bool = False) -> Dict[str, Any]:
    """Try to bring sovereign OpenAI proxy up on 8091."""
    state = load_state()
    if not _recovery_allowed(state, "proxy") and not dry_run:
        return {"ok": False, "reason": "max_recovery_attempts", "attempts": state["recovery_attempts"]["proxy"]}

    if dry_run:
        return {"ok": True, "dry_run": True, "would_run": str(START_PROXY_PS1)}

    proxy_script = START_PROXY_PS1 if START_PROXY_PS1.is_file() else START_PROXY_LEGACY_PS1
    if not proxy_script.is_file():
        return {"ok": False, "reason": "start_script_missing"}

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(proxy_script)],
            cwd=str(HERMES_SCRIPTS),
            capture_output=True,
            text=True,
            timeout=60,
        )
        state.setdefault("recovery_attempts", {})["proxy"] = int(state["recovery_attempts"].get("proxy", 0)) + 1
        state["last_proxy_recovery"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        matrix = tier_matrix()
        return {
            "ok": matrix.get("proxy_ready", False),
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-500:],
            "matrix": matrix,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _llama_start_script() -> Path:
    if _unified_mode_enabled() and START_LLAMA_PS1.is_file():
        return START_LLAMA_PS1
    if START_UNIFIED_PS1.is_file():
        return START_UNIFIED_PS1
    return START_MOE_PS1


def attempt_moe_recovery(dry_run: bool = False) -> Dict[str, Any]:
    """Bring llama :8090 up — unified mode uses 02-start-llama.ps1."""
    state = load_state()
    if not _recovery_allowed(state, "moe") and not dry_run:
        return {"ok": False, "reason": "max_recovery_attempts", "attempts": state["recovery_attempts"]["moe"]}

    script = _llama_start_script()
    if dry_run:
        return {"ok": True, "dry_run": True, "would_run": str(script)}

    if not script.is_file():
        return {"ok": False, "reason": "start_script_missing", "path": str(script)}

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(HERMES_SCRIPTS),
            capture_output=True,
            text=True,
            timeout=180,
        )
        state.setdefault("recovery_attempts", {})["moe"] = int(state["recovery_attempts"].get("moe", 0)) + 1
        state["last_recovery"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        matrix = tier_matrix(force_refresh=True)
        return {
            "ok": matrix.get("moe_ready", False),
            "script": script.name,
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-500:],
            "matrix": matrix,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def preflight_for_agent(auto_recover: bool = False) -> Dict[str, Any]:
    matrix = tier_matrix()
    result: Dict[str, Any] = {"matrix": matrix, "recovered": False, "recoveries": []}

    if matrix.get("agent_local_ready"):
        result["cooldown_reset"] = reset_recovery_counters_on_green(matrix)
        result["ok"] = True
        return result

    if auto_recover:
        if not matrix.get("moe_ready"):
            recovery = attempt_moe_recovery()
            result["recoveries"].append({"target": "moe", **recovery})
            matrix = tier_matrix()
            result["matrix"] = matrix

        if matrix.get("moe_ready") and not matrix.get("proxy_ready"):
            proxy_recovery = attempt_proxy_recovery()
            result["recoveries"].append({"target": "proxy", **proxy_recovery})
            matrix = tier_matrix()
            result["matrix"] = matrix

        result["recovered"] = any(r.get("ok") for r in result["recoveries"])

    result["ok"] = matrix.get("agent_local_ready", False)
    if result["ok"]:
        result["cooldown_reset"] = reset_recovery_counters_on_green(matrix)
    return result


def append_watchdog_log(event: Dict[str, Any]) -> None:
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="MoE model resource manager")
    parser.add_argument("--matrix", action="store_true", help="Print tier port matrix JSON")
    parser.add_argument("--recover", action="store_true", help="Attempt MoE stack recovery")
    parser.add_argument("--recover-proxy", action="store_true", help="Attempt proxy recovery on 8091")
    parser.add_argument("--preflight", action="store_true", help="Agent preflight with optional auto-recover")
    parser.add_argument("--auto-recover", action="store_true", help="Use with --preflight to self-heal")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.recover:
        print(json.dumps(attempt_moe_recovery(dry_run=args.dry_run), indent=2))
        return 0

    if args.recover_proxy:
        print(json.dumps(attempt_proxy_recovery(dry_run=args.dry_run), indent=2))
        return 0

    if args.preflight:
        print(json.dumps(preflight_for_agent(auto_recover=args.auto_recover), indent=2))
        return 0

    print(json.dumps(tier_matrix(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
