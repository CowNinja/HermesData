#!/usr/bin/env python3
"""
ensure_hermes_sovereign_config.py — Persist Phronesis MoE Hermes config (64K + P1 routing).

Hermes Agent requires model.context_length >= 64000. The phronesis-moe-gateway (8091) advertises
a flat 64K window while trimming payloads per MoE tier before llama-server dispatch.

Also enforces P1 local-first defaults:
  - delegation → phronesis-sovereign-code @ 8091 (no Grok subagent leak)
  - auxiliary.compression → phronesis-sovereign-synthesis (8082 warm digest)
  - local_sovereign per-step routing flags

Run automatically from Start-Sovereign-Proxy-8091.ps1 and sovereign_openai_proxy.py boot.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_DATA_CONFIG = Path(r"D:\HermesData\config.yaml")
HERMES_USER_CONFIG = Path.home() / ".hermes" / "config.yaml"
SOVEREIGN_PROVIDER = "phronesis-sovereign"
MOE_GATEWAY_URL = "http://127.0.0.1:8091/v1"
CORE_CONFIG = Path(r"D:\HermesData\scripts\phronesis-core.json")
DEFAULT_CONTEXT = 65536
HERMES_MIN_CONTEXT = 64000


def _target_context_length() -> int:
    try:
        if CORE_CONFIG.is_file():
            core = json.loads(CORE_CONFIG.read_text(encoding="utf-8"))
            ctx = int(core.get("ctx_size") or 0)
            if ctx >= 4096:
                return max(ctx, HERMES_MIN_CONTEXT)
    except Exception:
        pass
    return max(DEFAULT_CONTEXT, HERMES_MIN_CONTEXT)


MIN_CONTEXT = _target_context_length()

DELEGATION_DEFAULTS = {
    "model": "phronesis-sovereign-code",
    "provider": SOVEREIGN_PROVIDER,
    "base_url": MOE_GATEWAY_URL,
    "api_key": "local",
    "api_mode": "chat_completions",
}

COMPRESSION_DEFAULTS = {
    "provider": "custom",
    "model": "phronesis-sovereign-synthesis",
    "base_url": MOE_GATEWAY_URL,
    "api_key": "local",
    "timeout": 360,
}

MODEL_DEFAULTS = {
    "default": "phronesis-sovereign-auto",
    "provider": "custom:phronesis-sovereign",
    "base_url": MOE_GATEWAY_URL,
    "context_length": MIN_CONTEXT,
}

FALLBACK_SOVEREIGN_ONLY = [
    {
        "provider": f"custom:{SOVEREIGN_PROVIDER}",
        "model": "phronesis-sovereign-auto",
        "base_url": MOE_GATEWAY_URL,
        "api_key": "local",
    },
]

_CLOUD_FALLBACK_PROVIDERS = frozenset(
    {"openrouter", "xai-oauth", "xai", "nous", "anthropic", "openai", "gemini", "copilot"}
)

SOVEREIGN_ENVIRONMENT_HINT = (
    f"Phronesis Sovereign Stack: Qwythos-9B Q6_K @ {MIN_CONTEXT} ctx on llama-server:8090 "
    "via phronesis-sovereign proxy:8091. Model rotation is LOCKED — 9B only, no 14B "
    "fallback. ALWAYS invoke terminal/file tools for factual queries (disk space, "
    "file listings, system state) — never hallucinate command output. Deliver clean "
    "final answers only; no scratch reasoning in replies."
)

LOCAL_SOVEREIGN_DEFAULTS = {
    "gateway_name": "phronesis-moe-gateway",
    "subagent_default_model": "phronesis-sovereign-code",
    "subagent_synthesis_model": "phronesis-sovereign-synthesis",
    "subagent_classify_model": "phronesis-sovereign-classify",
    "per_step_routing": True,
    "mode": "unified_8090",
    "router_mode": "unified_8090",
    "tiers": {
        "unified": 8090,
        "hot": 8090,
        "warm": 8090,
        "classifier": 8090,
        "proxy": 8091,
    },
}

EXTRA_SOVEREIGN_MODELS = (
    "phronesis-sovereign-classify",
    "phronesis-sovereign-metadata",
)

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.is_file():
        return None, "missing"
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        return None, text
    try:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            return None, text
        return data, text
    except Exception as exc:
        return None, f"parse_error:{exc}"


def _dump_yaml(data: Dict[str, Any]) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML not installed")
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _patch_structured(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    changes: List[str] = []
    patched = deepcopy(data)

    model = patched.setdefault("model", {})
    if not isinstance(model, dict):
        model = {}
        patched["model"] = model
    local_sovereign = patched.get("local_sovereign") or {}
    force_local = isinstance(local_sovereign, dict) and local_sovereign.get("force_local") is not False
    current_provider = str(model.get("provider") or "").strip().lower()
    leaked_cloud = current_provider in {
        "xai-oauth",
        "xai",
        "nous",
        "openrouter",
        "anthropic",
        "openai",
        "gemini",
    } or current_provider.startswith("custom:") and "phronesis-sovereign" not in current_provider
    if force_local and (leaked_cloud or not str(model.get("default") or "").startswith("phronesis-sovereign")):
        for key, value in MODEL_DEFAULTS.items():
            if model.get(key) != value:
                model[key] = value
                changes.append(f"model.{key}")
    if int(model.get("context_length") or 0) != MIN_CONTEXT:
        model["context_length"] = MIN_CONTEXT
        changes.append("model.context_length")

    providers = patched.get("custom_providers") or []
    if not isinstance(providers, list):
        providers = []
        patched["custom_providers"] = providers

    for prov in providers:
        if not isinstance(prov, dict):
            continue
        if prov.get("name") != SOVEREIGN_PROVIDER:
            continue
        if int(prov.get("context_length") or 0) != MIN_CONTEXT:
            prov["context_length"] = MIN_CONTEXT
            changes.append(f"{SOVEREIGN_PROVIDER}.context_length")
        models = prov.get("models") or {}
        if isinstance(models, dict):
            for model_id, model_cfg in models.items():
                if not isinstance(model_cfg, dict):
                    model_cfg = {}
                    models[model_id] = model_cfg
                if int(model_cfg.get("context_length") or 0) != MIN_CONTEXT:
                    model_cfg["context_length"] = MIN_CONTEXT
                    changes.append(f"{SOVEREIGN_PROVIDER}.models.{model_id}.context_length")
        for model_id in EXTRA_SOVEREIGN_MODELS:
            block = models.setdefault(model_id, {})
            if not isinstance(block, dict):
                block = {}
                models[model_id] = block
            if int(block.get("context_length") or 0) != MIN_CONTEXT:
                block["context_length"] = MIN_CONTEXT
                changes.append(f"{SOVEREIGN_PROVIDER}.models.{model_id}.context_length")
        prov["models"] = models

    delegation = patched.setdefault("delegation", {})
    if isinstance(delegation, dict):
        for key, value in DELEGATION_DEFAULTS.items():
            current = delegation.get(key)
            if not str(current or "").strip():
                delegation[key] = value
                changes.append(f"delegation.{key}")

    auxiliary = patched.setdefault("auxiliary", {})
    if isinstance(auxiliary, dict):
        compression = auxiliary.setdefault("compression", {})
        if isinstance(compression, dict):
            old_url = str(compression.get("base_url") or "")
            old_model = str(compression.get("model") or "")
            old_provider = str(compression.get("provider") or "").strip().lower()
            if (
                "11434" in old_url
                or "ollama" in old_model.lower()
                or not old_model
                or old_provider in ("auto", "")
                or "phronesis-sovereign" not in old_model
            ):
                compression.update(COMPRESSION_DEFAULTS)
                compression["provider"] = f"custom:{SOVEREIGN_PROVIDER}"
                changes.append("auxiliary.compression→8091-synthesis")

    if force_local:
        fallback = patched.get("fallback_model")
        entries: List[Dict[str, Any]] = []
        if isinstance(fallback, list):
            entries = [e for e in fallback if isinstance(e, dict)]
        elif isinstance(fallback, dict) and fallback.get("provider") and fallback.get("model"):
            entries = [fallback]
        has_cloud = any(
            str(e.get("provider") or "").strip().lower() in _CLOUD_FALLBACK_PROVIDERS
            or str(e.get("provider") or "").strip().lower().startswith("custom:")
            and "phronesis-sovereign" not in str(e.get("provider") or "").lower()
            for e in entries
        )
        if has_cloud or len(entries) != 1 or entries[0].get("provider") != f"custom:{SOVEREIGN_PROVIDER}":
            patched["fallback_model"] = deepcopy(FALLBACK_SOVEREIGN_ONLY)
            changes.append("fallback_model→sovereign-only")

    agent = patched.setdefault("agent", {})
    if isinstance(agent, dict):
        if agent.get("environment_hint") != SOVEREIGN_ENVIRONMENT_HINT:
            agent["environment_hint"] = SOVEREIGN_ENVIRONMENT_HINT
            changes.append("agent.environment_hint→9B-locked")
        if agent.get("reasoning_effort") not in (None, "", "low", "none"):
            agent["reasoning_effort"] = "low"
            changes.append("agent.reasoning_effort→low")
        if str(agent.get("tool_use_enforcement") or "").lower() in (
            "true", "always", "yes", "on",
        ):
            agent["tool_use_enforcement"] = "auto"
            changes.append("agent.tool_use_enforcement→auto")

    display = patched.setdefault("display", {})
    if isinstance(display, dict):
        if display.get("show_reasoning") is not False:
            display["show_reasoning"] = False
            changes.append("display.show_reasoning→false")
        if display.get("reasoning_full") is not False:
            display["reasoning_full"] = False
            changes.append("display.reasoning_full→false")
        platforms = display.setdefault("platforms", {})
        if isinstance(platforms, dict):
            discord = platforms.setdefault("discord", {})
            if isinstance(discord, dict):
                if discord.get("show_reasoning") is not False:
                    discord["show_reasoning"] = False
                    changes.append("display.platforms.discord.show_reasoning→false")
                if discord.get("streaming") is not False:
                    discord["streaming"] = False
                    changes.append("display.platforms.discord.streaming→false")

    local_sovereign = patched.setdefault("local_sovereign", {})
    if isinstance(local_sovereign, dict):
        if local_sovereign.get("opportunistic_fleet", {}).get("enabled") is True:
            fleet = local_sovereign.setdefault("opportunistic_fleet", {})
            if isinstance(fleet, dict):
                fleet["enabled"] = False
                changes.append("local_sovereign.opportunistic_fleet.enabled→false")
        for key, value in LOCAL_SOVEREIGN_DEFAULTS.items():
            if key == "tiers" and isinstance(value, dict):
                tiers = local_sovereign.setdefault("tiers", {})
                if not isinstance(tiers, dict):
                    tiers = {}
                    local_sovereign["tiers"] = tiers
                for tk, tv in value.items():
                    if tiers.get(tk) in (None, "", 8081, 8082, 8083):
                        if tiers.get(tk) != tv:
                            tiers[tk] = tv
                            changes.append(f"local_sovereign.tiers.{tk}")
                continue
            if local_sovereign.get(key) in (None, ""):
                local_sovereign[key] = value
                changes.append(f"local_sovereign.{key}")

    return patched, changes


def _patch_regex_fallback(text: str) -> Tuple[str, List[str]]:
    """Targeted line edits when PyYAML is unavailable."""
    changes: List[str] = []
    out = text

    def _sub(pattern: str, repl: str, label: str, src: str) -> str:
        nonlocal changes
        new, n = re.subn(pattern, repl, src, count=1, flags=re.MULTILINE)
        if n:
            changes.append(label)
        return new

    out = _sub(
        r"(^model:\s*\n(?:[ \t].*\n)*?[ \t]+context_length:\s*)\d+",
        rf"\g<1>{MIN_CONTEXT}",
        "model.context_length",
        out,
    )
    if "model.context_length" not in changes and re.search(r"^model:\s*$", out, re.MULTILINE):
        out = re.sub(
            r"(^model:\s*\n)",
            rf"\1  context_length: {MIN_CONTEXT}\n",
            out,
            count=1,
            flags=re.MULTILINE,
        )
        changes.append("model.context_length(insert)")

    sovereign_block = re.search(
        rf"(^[ \t]*- name: {re.escape(SOVEREIGN_PROVIDER)}\s*\n(?:[ \t].*\n)*?)",
        out,
        re.MULTILINE,
    )
    if sovereign_block:
        block = sovereign_block.group(1)
        new_block, n = re.subn(
            r"(^[ \t]+context_length:\s*)\d+",
            rf"\g<1>{MIN_CONTEXT}",
            block,
            count=0,
            flags=re.MULTILINE,
        )
        if n:
            changes.append(f"{SOVEREIGN_PROVIDER}.context_length*")
            out = out[: sovereign_block.start(1)] + new_block + out[sovereign_block.end(1) :]

    return out, changes


def ensure_config(path: Path, dry_run: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "changed": False,
        "changes": [],
        "method": None,
        "error": None,
    }
    if not path.is_file():
        result["error"] = "missing"
        return result

    backup = path.with_suffix(path.suffix + f".bak-ctx-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

    data, raw = _load_yaml(path)
    if isinstance(data, dict):
        patched, changes = _patch_structured(data)
        if changes:
            result["method"] = "yaml"
            result["changes"] = changes
            if not dry_run:
                backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                path.write_text(_dump_yaml(patched), encoding="utf-8")
            result["changed"] = True
            result["backup"] = str(backup) if not dry_run else None
        return result

    if isinstance(raw, str):
        new_text, changes = _patch_regex_fallback(raw)
        if changes:
            result["method"] = "regex"
            result["changes"] = changes
            if not dry_run:
                backup.write_text(raw, encoding="utf-8")
                path.write_text(new_text, encoding="utf-8")
            result["changed"] = True
            result["backup"] = str(backup) if not dry_run else None
        return result

    result["error"] = raw
    return result


SOVEREIGN_MODEL_IDS = (
    "phronesis-sovereign-auto",
    "phronesis-sovereign-code",
    "phronesis-sovereign-synthesis",
    "phronesis-sovereign-classify",
    "phronesis-sovereign-metadata",
    "phronesis-sovereign-roleplay",
    "phronesis-sovereign-hot",
    "phronesis-sovereign-warm",
    "phronesis-sovereign-deep",
)


def _write_context_length_cache_yaml(path: Path, entries: Dict[str, int], dry_run: bool) -> None:
    if dry_run or not entries:
        return
    existing: Dict[str, int] = {}
    if path.is_file():
        try:
            if yaml is not None:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                raw = data.get("context_lengths") or {}
                if isinstance(raw, dict):
                    existing = {str(k): int(v) for k, v in raw.items() if v}
        except Exception:
            pass
    merged = {**existing, **entries}
    lines = ["context_lengths:"]
    for key in sorted(merged):
        lines.append(f"  {key}: {merged[key]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def seed_context_length_cache(dry_run: bool = False) -> Dict[str, Any]:
    """Persist 64K context for every phronesis-sovereign model @ 8091."""
    cache_paths = [
        HERMES_USER_CONFIG.parent / "context_length_cache.yaml",
        HERMES_DATA_CONFIG.parent / "context_length_cache.yaml",
    ]
    entries = {
        f"{model_id}@{MOE_GATEWAY_URL.rstrip('/')}": MIN_CONTEXT
        for model_id in SOVEREIGN_MODEL_IDS
    }
    for cache_path in cache_paths:
        _write_context_length_cache_yaml(cache_path, entries, dry_run)
    return {
        "ok": True,
        "context": MIN_CONTEXT,
        "models": list(SOVEREIGN_MODEL_IDS),
        "cache_paths": [str(p) for p in cache_paths],
    }


def ensure_all_configs(dry_run: bool = False) -> Dict[str, Any]:
    paths = [HERMES_DATA_CONFIG, HERMES_USER_CONFIG]
    reports = [ensure_config(p, dry_run=dry_run) for p in paths]
    cache_report = seed_context_length_cache(dry_run=dry_run)
    return {
        "timestamp": _utc_now(),
        "min_context": MIN_CONTEXT,
        "provider": SOVEREIGN_PROVIDER,
        "changed": any(r.get("changed") for r in reports),
        "configs": reports,
        "context_cache": cache_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure Hermes sovereign 64K context config")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = ensure_all_configs(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for cfg in report["configs"]:
            status = "PATCHED" if cfg.get("changed") else "OK"
            print(f"{status}: {cfg.get('path')}")
            if cfg.get("changes"):
                for ch in cfg["changes"]:
                    print(f"  - {ch}")
            if cfg.get("error"):
                print(f"  error: {cfg['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
