#!/usr/bin/env python3
"""Phase 8a T2 SFW image offload -- modular provider adapters via fleet_registry.yaml."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCRIPTS = Path(__file__).resolve().parent
REGISTRY_PATH = Path(r"D:\HermesData\config\fleet_registry.yaml")

if str(SCRIPTS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS))

from fleet_sfw_gate import classify_image_offload  # noqa: E402


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def list_image_providers(*, enabled_only: bool = True) -> List[Dict[str, Any]]:
    reg = _load_yaml(REGISTRY_PATH)
    providers = reg.get("image_providers") or []
    out: List[Dict[str, Any]] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        if enabled_only and not item.get("enabled", True):
            continue
        out.append(item)
    out.sort(key=lambda p: int(p.get("priority") or 99))
    return out


def _pollinations_generate(prompt: str, provider: Dict[str, Any]) -> Dict[str, Any]:
    base = str(provider.get("base_url") or "https://image.pollinations.ai/prompt").rstrip("/")
    encoded = urllib.parse.quote(prompt, safe="")
    width = int(provider.get("width") or 1024)
    height = int(provider.get("height") or 1024)
    url = f"{base}/{encoded}?width={width}&height={height}&nologo=true"
    timeout = float(provider.get("timeout_sec") or 45.0)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return {"success": False, "error": f"http_{resp.status}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "image": url,
        "model": str(provider.get("model") or "pollinations-generic"),
        "provider": str(provider.get("id") or "pollinations-sfw"),
    }


_ADAPTERS: Dict[str, Callable[[str, Dict[str, Any]], Dict[str, Any]]] = {
    "pollinations": _pollinations_generate,
}


def try_fleet_image_generate(
    prompt: str,
    *,
    aspect_ratio: str = "1:1",
) -> Dict[str, Any]:
    """Attempt T2 SFW image generation. Returns success_response shape or error dict."""
    gate = classify_image_offload(prompt)
    if not gate.get("allow_t2"):
        return {
            "success": False,
            "error": f"t2_gate_blocked:{gate.get('reason')}",
            "route": gate.get("route", "local_comfy_only"),
        }

    sanitized = str(gate.get("sanitized_prompt") or prompt)
    providers = list_image_providers()
    if not providers:
        return {"success": False, "error": "no_image_providers_configured"}

    errors: List[str] = []
    for provider in providers:
        mode = str(provider.get("api_mode") or provider.get("adapter") or "").lower()
        fn = _ADAPTERS.get(mode)
        if fn is None:
            errors.append(f"unknown_adapter:{mode}")
            continue
        result = fn(sanitized, provider)
        if result.get("success"):
            result["route"] = "t2_image_optional"
            result["aspect_ratio"] = aspect_ratio
            result["prompt"] = sanitized
            result["gate_reason"] = gate.get("reason")
            return result
        errors.append(str(result.get("error") or "provider_fail"))

    return {"success": False, "error": ";".join(errors) or "all_providers_failed"}


def main() -> int:
    prompt = "landscape mountain sunset"
    if len(__import__("sys").argv) > 1:
        prompt = " ".join(__import__("sys").argv[1:])
    gate = classify_image_offload(prompt)
    print(json.dumps({"gate": gate}))
    if not gate.get("allow_t2"):
        return 0
    result = try_fleet_image_generate(prompt)
    print(json.dumps(result))
    # Gate pass is the smoke criterion; provider 403 is logged not fatal
    if result.get("success"):
        return 0
    err = str(result.get("error") or "")
    if "403" in err or "Forbidden" in err:
        print(json.dumps({"smoke": "gate_ok_provider_blocked", "note": "pollinations_may_rate_limit"}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())