#!/usr/bin/env python3
"""
ensure_hermes_sovereign_config.py ? Persist Phronesis MoE Hermes config (64K + P1 routing).

Hermes Agent requires model.context_length >= 64000. The phronesis-moe-gateway (8091) advertises
a flat 64K window while trimming payloads per MoE tier before llama-server dispatch.

Also enforces P1 local-first defaults:
  - delegation ? phronesis-sovereign-code @ 8091 (no Grok subagent leak)
  - auxiliary.compression ? phronesis-sovereign-synthesis (8082 warm digest)
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
DEFAULT_CONTEXT = 131072  # SSOT: phronesis-core.json ctx_size (raised 2026-08-03)
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

# Single SSOT hint. Must include interview UX so boot ensure + interview heal
# do NOT thrash config.yaml (was: ensure strips interview, heal re-adds -> bak storm).
SOVEREIGN_ENVIRONMENT_HINT = (
    f"Phronesis Sovereign Stack: Qwythos-9B Q6_K @ {MIN_CONTEXT} ctx on llama-server:8090 "
    "via phronesis-sovereign proxy:8091. Model rotation is LOCKED - 9B only, no 14B "
    "fallback. ALWAYS invoke terminal/file tools for factual queries (disk space, "
    "file listings, system state) - never hallucinate command output. Deliver clean "
    "final answers only; no scratch reasoning in replies. INTERVIEW/CLARIFY UX: never "
    "fake dialogue with Jeff; multi-choice = one clarify(4) then STOP, or one batch of "
    "<=10 A-D (~2k chars); no MCQ novels; no invent skills; no [Called ...] leaks. "
    "Skills: discord-clarify-interview, jeff-about-me-interview (About-me thread)."
)

# Idempotency: if all markers present, do not rewrite (avoids bak-ctx thrash every proxy boot).
_HINT_OK_MARKERS = (
    "Qwythos-9B",
    "proxy:8091",
    "9B only",
    "INTERVIEW/CLARIFY",
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


def _is_cloud_primary_model(model: Dict[str, Any]) -> bool:
    provider = str(model.get("provider") or "").strip().lower()
    if provider in _CLOUD_FALLBACK_PROVIDERS:
        return True
    return provider.startswith("custom:") and "phronesis-sovereign" not in provider


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
    cloud_primary = _is_cloud_primary_model(model)
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
    # Cloud primaries (e.g. grok-4.5 @ 500k) must keep their large context_length.
    # Forcing 65536 here caused endless Discord compaction loops.
    if not cloud_primary:
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
            sovereign_compression = (
                "phronesis-sovereign" in old_model.lower()
                or old_provider in ("phronesis-sovereign", f"custom:{SOVEREIGN_PROVIDER}".lower())
                or "8091" in old_url
            )
            if cloud_primary and not force_local and sovereign_compression:
                compression.clear()
                compression["provider"] = "auto"
                compression["timeout"] = 360
                changes.append("auxiliary.compression?auto(cloud-primary)")
            elif not cloud_primary and (
                "11434" in old_url
                or "ollama" in old_model.lower()
                or not old_model
                or old_provider in ("auto", "")
                or "phronesis-sovereign" not in old_model
            ):
                compression.update(COMPRESSION_DEFAULTS)
                compression["provider"] = f"custom:{SOVEREIGN_PROVIDER}"
                changes.append("auxiliary.compression?8091-synthesis")
            # Always pin compress window to live Qwythos n_ctx (Hermes floor >=64k)
            if not cloud_primary or force_local:
                try:
                    cctx = int(compression.get("context_length") or 0)
                except (TypeError, ValueError):
                    cctx = 0
                if cctx != MIN_CONTEXT:
                    compression["context_length"] = MIN_CONTEXT
                    changes.append("auxiliary.compression.context_length")
                # Prefer auto@full-ctx over classify (classify was mis-detected as 32k)
                m = str(compression.get("model") or "")
                if "classify" in m.lower() or not m:
                    compression["model"] = "phronesis-sovereign-auto"
                    compression["provider"] = f"custom:{SOVEREIGN_PROVIDER}"
                    compression["base_url"] = MOE_GATEWAY_URL
                    compression["api_key"] = "local"
                    changes.append("auxiliary.compression.model->auto")

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
            changes.append("fallback_model?sovereign-only")

    agent = patched.setdefault("agent", {})
    if isinstance(agent, dict):
        hint = str(agent.get("environment_hint") or "")
        # Marker-based ok (not exact equality): exact match fought interview heal every boot.
        if not all(m in hint for m in _HINT_OK_MARKERS):
            agent["environment_hint"] = SOVEREIGN_ENVIRONMENT_HINT
            changes.append("agent.environment_hint?9B-locked+interview")
        if agent.get("reasoning_effort") not in (None, "", "low", "none"):
            agent["reasoning_effort"] = "low"
            changes.append("agent.reasoning_effort?low")
        # config.yaml uses "strict"; do not thrash strict -> auto on every boot
        tue = str(agent.get("tool_use_enforcement") or "").lower()
        if tue in ("true", "always", "yes", "on"):
            agent["tool_use_enforcement"] = "strict"
            changes.append("agent.tool_use_enforcement?strict")

    display = patched.setdefault("display", {})
    if isinstance(display, dict):
        if display.get("show_reasoning") is not False:
            display["show_reasoning"] = False
            changes.append("display.show_reasoning?false")
        if display.get("reasoning_full") is not False:
            display["reasoning_full"] = False
            changes.append("display.reasoning_full?false")
        platforms = display.setdefault("platforms", {})
        if isinstance(platforms, dict):
            discord = platforms.setdefault("discord", {})
            if isinstance(discord, dict):
                if discord.get("show_reasoning") is not False:
                    discord["show_reasoning"] = False
                    changes.append("display.platforms.discord.show_reasoning?false")
                if discord.get("streaming") is not False:
                    discord["streaming"] = False
                    changes.append("display.platforms.discord.streaming?false")

    local_sovereign = patched.setdefault("local_sovereign", {})
    if isinstance(local_sovereign, dict):
        fleet = local_sovereign.setdefault("opportunistic_fleet", {})
        if isinstance(fleet, dict):
            if fleet.get("registry") in (None, ""):
                fleet["registry"] = "D:/HermesData/config/fleet_registry.yaml"
                changes.append("local_sovereign.opportunistic_fleet.registry")
            if fleet.get("prefer_free_before_grok") is None:
                fleet["prefer_free_before_grok"] = True
                changes.append("local_sovereign.opportunistic_fleet.prefer_free_before_grok?true")
            if fleet.get("augment_local_with_context") is None:
                fleet["augment_local_with_context"] = True
                changes.append("local_sovereign.opportunistic_fleet.augment_local_with_context?true")
            if fleet.get("fallback_on_local_fail") is None:
                fleet["fallback_on_local_fail"] = True
                changes.append("local_sovereign.opportunistic_fleet.fallback_on_local_fail?true")
            if fleet.get("proactive_realtime_triggers") is None:
                fleet["proactive_realtime_triggers"] = True
                changes.append("local_sovereign.opportunistic_fleet.proactive_realtime_triggers?true")
            if fleet.get("proactive_offload") is None:
                fleet["proactive_offload"] = True
                changes.append("local_sovereign.opportunistic_fleet.proactive_offload->true")
            # Policy B (2026-07-27): auto Grok for hard reasoning only; thrift caps 5%/20%
            if fleet.get("grok_policy") in (None, ""):
                fleet["grok_policy"] = "B"
                changes.append("local_sovereign.opportunistic_fleet.grok_policy->B")
            if fleet.get("hard_prompt_auto_t3") is None:
                fleet["hard_prompt_auto_t3"] = True
                changes.append("local_sovereign.opportunistic_fleet.hard_prompt_auto_t3->true")
            if fleet.get("grok_share_cap_yellow") is None:
                fleet["grok_share_cap_yellow"] = 0.05
                changes.append("local_sovereign.opportunistic_fleet.grok_share_cap_yellow->0.05")
            if fleet.get("grok_share_cap_red") is None:
                fleet["grok_share_cap_red"] = 0.20
                changes.append("local_sovereign.opportunistic_fleet.grok_share_cap_red->0.20")
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

    grok_auth = patched.setdefault("grok_auth", {})
    if isinstance(grok_auth, dict):
        if grok_auth.get("prefer_subscription") is None:
            grok_auth["prefer_subscription"] = True
            changes.append("grok_auth.prefer_subscription->true")
        if grok_auth.get("oauth_refresh_on_auth_fail") is None:
            grok_auth["oauth_refresh_on_auth_fail"] = True
            changes.append("grok_auth.oauth_refresh_on_auth_fail->true")
        if not grok_auth.get("fallback_http_codes"):
            grok_auth["fallback_http_codes"] = [401, 403, 404]
            changes.append("grok_auth.fallback_http_codes")
        if grok_auth.get("transient_retry") is None:
            grok_auth["transient_retry"] = True
            changes.append("grok_auth.transient_retry->true")
        if grok_auth.get("rate_limit_retries") is None:
            grok_auth["rate_limit_retries"] = 2
            changes.append("grok_auth.rate_limit_retries->2")
        if grok_auth.get("rate_limit_max_wait_sec") is None:
            grok_auth["rate_limit_max_wait_sec"] = 120
            changes.append("grok_auth.rate_limit_max_wait_sec->120")
        # Treat quota/token exhaustion as retriable then fall through to local/free path
        codes = list(grok_auth.get("fallback_http_codes") or [])
        for code in (402, 429):
            if code not in codes:
                codes.append(code)
                changes.append(f"grok_auth.fallback_http_codes+{code}")
        grok_auth["fallback_http_codes"] = codes

    # Discord channel_overrides must not bypass sovereign router with direct xai-oauth.
    # Full RP classification lives in enforce_sovereign_router_entry.py; here we only
    # strip hard Grok pins so Discord never defaults past :8091.
    if force_local:
        discord = patched.setdefault("discord", {})
        if isinstance(discord, dict):
            overrides = discord.get("channel_overrides") or {}
            if isinstance(overrides, dict):
                n_fixed = 0
                for cid, ov in overrides.items():
                    if not isinstance(ov, dict):
                        continue
                    prov = str(ov.get("provider") or "").lower()
                    model = str(ov.get("model") or "").lower()
                    if "xai" in prov or "grok" in model:
                        ov["provider"] = "custom:phronesis-sovereign"
                        if "roleplay" not in model and "rp" not in model:
                            ov["model"] = "phronesis-sovereign-auto"
                        else:
                            ov["model"] = "phronesis-sovereign-roleplay"
                        try:
                            ctx = int(ov.get("context_length") or 0)
                        except Exception:
                            ctx = 0
                        if ctx != MIN_CONTEXT:
                            ov["context_length"] = MIN_CONTEXT
                        n_fixed += 1
                # Raise/align all local override windows to SSOT (not only xai depins)
                n_ctx_align = 0
                for cid, ov in overrides.items():
                    if not isinstance(ov, dict):
                        continue
                    try:
                        ctx = int(ov.get("context_length") or 0)
                    except Exception:
                        ctx = 0
                    if ctx != MIN_CONTEXT:
                        ov["context_length"] = MIN_CONTEXT
                        n_ctx_align += 1
                if n_fixed:
                    changes.append(f"discord.channel_overrides.depin_xai={n_fixed}")
                if n_ctx_align:
                    changes.append(f"discord.channel_overrides.ctx_align={n_ctx_align}")
        # Stamp mandatory router entry doctrine
        if isinstance(local_sovereign, dict):
            entry = local_sovereign.get("router_entry")
            if not isinstance(entry, dict) or not entry.get("mandatory"):
                local_sovereign["router_entry"] = {
                    "mandatory": True,
                    "entry": "http://127.0.0.1:8091/v1",
                    "provider": "custom:phronesis-sovereign",
                    "default_model": "phronesis-sovereign-auto",
                    "roleplay_model": "phronesis-sovereign-roleplay",
                    "policy": {
                        "private_explicit_secrets": "local_only",
                        "grunt": "local_then_free",
                        "novel_high_value": "grok_optional_via_proxy_t3",
                        "token_exhaustion": "never_hard_fail_use_local_free",
                    },
                }
                changes.append("local_sovereign.router_entry.mandatory")

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


def _run_interview_ux_heal(dry_run: bool = False) -> Dict[str, Any]:
    """System-wide Discord clarify/interview UX (no fake dialogue / MCQ novels).

    Soft-depends on heal_discord_interview_ux_20260803.py. Skips when already
    marked healthy to stop bak-interview-ux-ensure storms on every proxy boot.
    """
    heal_path = Path(__file__).resolve().parent / "heal_discord_interview_ux_20260803.py"
    out: Dict[str, Any] = {"ok": False, "skipped": False, "path": str(heal_path)}
    if not heal_path.is_file():
        out["skipped"] = True
        out["error"] = "heal script missing"
        return out
    # Fast path: live config already has interview markers + universal law.
    try:
        raw = HERMES_DATA_CONFIG.read_text(encoding="utf-8") if HERMES_DATA_CONFIG.is_file() else ""
        if (
            "INTERVIEW/CLARIFY" in raw
            and "UNIVERSAL INTERVIEW/CLARIFY UX LAW" in raw
            and "discord-clarify-interview" in raw
        ):
            out["ok"] = True
            out["skipped"] = True
            out["changed"] = False
            out["reason"] = "already_marked_healthy"
            return out
    except Exception:
        pass
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("heal_discord_interview_ux", heal_path)
        if spec is None or spec.loader is None:
            out["error"] = "import_spec_failed"
            return out
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg_path = HERMES_DATA_CONFIG
        if not cfg_path.is_file():
            out["error"] = "config_missing"
            return out
        cfg = mod._load(cfg_path)
        report = mod.heal(cfg)
        out["report"] = report
        out["ok"] = True
        if report.get("changes") and not dry_run:
            bak = cfg_path.with_name(
                cfg_path.name
                + f".bak-interview-ux-ensure-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            bak.write_text(cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
            mod._dump(cfg_path, cfg)
            out["backup"] = str(bak)
            out["changed"] = True
        else:
            out["changed"] = False
            out["dry_run"] = bool(dry_run)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def ensure_all_configs(dry_run: bool = False) -> Dict[str, Any]:
    paths = [HERMES_DATA_CONFIG, HERMES_USER_CONFIG]
    reports = [ensure_config(p, dry_run=dry_run) for p in paths]
    cache_report = seed_context_length_cache(dry_run=dry_run)
    interview_ux = _run_interview_ux_heal(dry_run=dry_run)
    return {
        "timestamp": _utc_now(),
        "min_context": MIN_CONTEXT,
        "provider": SOVEREIGN_PROVIDER,
        "changed": any(r.get("changed") for r in reports) or bool(interview_ux.get("changed")),
        "configs": reports,
        "context_cache": cache_report,
        "interview_ux_heal": interview_ux,
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
