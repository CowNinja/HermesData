#!/usr/bin/env python3
"""Preflight invariant checks for Hermes + Phronesis stack config.

Catches recurrence of known footguns (65536 on Grok, sovereign compression loop,
missing fallback, stale context cache). Exit 0 = all checks pass; 1 = failures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES_DATA = Path(r"D:\HermesData\config.yaml")
HERMES_USER = Path.home() / ".hermes" / "config.yaml"
CACHE_USER = Path.home() / ".hermes" / "context_length_cache.yaml"

CLOUD_PROVIDERS = frozenset({"xai-oauth", "xai", "openrouter", "nous", "anthropic", "openai", "gemini"})

REQUIRED_CACHE = {
    "grok-4.5": 500_000,
    "grok-4.5@xai-oauth": 500_000,
    "grok-build-0.1": 256_000,
    "grok-build-0.1@xai-oauth": 256_000,
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _load_cache(path: Path) -> Dict[str, int]:
    data = _load_yaml(path)
    raw = data.get("context_lengths") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            pass
    return out


def check_config(path: Path, label: str) -> List[Tuple[str, str]]:
    """Return list of (severity, message). severity: fail | warn"""
    issues: List[Tuple[str, str]] = []
    if not path.is_file():
        issues.append(("fail", f"{label}: missing {path}"))
        return issues

    cfg = _load_yaml(path)
    model = cfg.get("model") or {}
    if not isinstance(model, dict):
        issues.append(("fail", f"{label}: model block invalid"))
        return issues

    provider = str(model.get("provider") or "").strip().lower()
    default = str(model.get("default") or "")
    ctx = model.get("context_length")
    cloud_primary = provider in CLOUD_PROVIDERS

    if cloud_primary and ctx is not None:
        try:
            ctx_i = int(ctx)
            issues.append(
                (
                    "fail",
                    f"{label}: global model.context_length={ctx_i} set while provider={provider} "
                    "- breaks grok-build-0.1 channel_overrides; use context_length_cache.yaml only",
                )
            )
        except (TypeError, ValueError):
            issues.append(("warn", f"{label}: model.context_length is non-integer"))

    aux = cfg.get("auxiliary") or {}
    compression = (aux.get("compression") or {}) if isinstance(aux, dict) else {}
    comp_provider = str(compression.get("provider") or "").strip().lower()
    comp_model = str(compression.get("model") or "").lower()
    comp_url = str(compression.get("base_url") or "")

    if cloud_primary:
        sovereign_comp = (
            "phronesis-sovereign" in comp_provider
            or "phronesis-sovereign" in comp_model
            or "8091" in comp_url
        )
        if sovereign_comp and comp_provider not in ("auto", ""):
            issues.append(
                (
                    "fail",
                    f"{label}: auxiliary.compression points at sovereign while Grok is primary "
                    f"(provider={comp_provider!r}) - causes Auto-lowered 65536 compaction loop",
                )
            )
        elif comp_provider not in ("auto", ""):
            issues.append(
                ("warn", f"{label}: auxiliary.compression.provider={comp_provider!r} (expected auto for Grok primary)")
            )

    local = cfg.get("local_sovereign") or {}
    if isinstance(local, dict) and local.get("force_local") is True and cloud_primary:
        issues.append(
            ("warn", f"{label}: local_sovereign.force_local=true with cloud primary - may override Grok routing")
        )

    fallback = cfg.get("fallback_model")
    has_sovereign_fb = False
    if isinstance(fallback, list):
        for entry in fallback:
            if isinstance(entry, dict) and "phronesis-sovereign" in str(entry.get("provider") or ""):
                has_sovereign_fb = True
    elif isinstance(fallback, dict) and fallback.get("provider"):
        has_sovereign_fb = "phronesis-sovereign" in str(fallback.get("provider"))

    if cloud_primary and not has_sovereign_fb:
        issues.append(("warn", f"{label}: no phronesis-sovereign entry in fallback_model"))

    if cloud_primary and default and not default.startswith("grok"):
        issues.append(("warn", f"{label}: model.default={default!r} (expected grok-* for current hybrid)"))

    return issues


def check_cache() -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    cache = _load_cache(CACHE_USER)
    if not cache:
        issues.append(("fail", f"context_length_cache missing or empty: {CACHE_USER}"))
        return issues
    for key, expected in REQUIRED_CACHE.items():
        got = cache.get(key)
        if got is None:
            issues.append(("warn", f"cache missing key {key!r} (expected {expected})"))
        elif got != expected:
            issues.append(
                (
                    "fail",
                    f"cache[{key!r}]={got} expected {expected} - compaction thresholds will be wrong",
                )
            )
    return issues


def main() -> int:
    as_json = "--json" in sys.argv
    all_issues: List[Dict[str, str]] = []

    for path, label in ((HERMES_DATA, "HermesData"), (HERMES_USER, "user")):
        for sev, msg in check_config(path, label):
            all_issues.append({"severity": sev, "check": label, "message": msg})

    for sev, msg in check_cache():
        all_issues.append({"severity": sev, "check": "cache", "message": msg})

    fails = [i for i in all_issues if i["severity"] == "fail"]
    warns = [i for i in all_issues if i["severity"] == "warn"]

    report = {
        "ok": len(fails) == 0,
        "fail_count": len(fails),
        "warn_count": len(warns),
        "issues": all_issues,
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for item in all_issues:
            tag = "FAIL" if item["severity"] == "fail" else "WARN"
            print(f"{tag}: {item['message']}")
        if not all_issues:
            print("OK: all stack config invariants passed")
        elif fails:
            print(f"\n{len(fails)} failure(s), {len(warns)} warning(s)")
        else:
            print(f"\n0 failures, {len(warns)} warning(s)")

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())