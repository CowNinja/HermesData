#!/usr/bin/env python3
"""
grok_auth.py - Uniform Grok auth for sovereign scripts.

First principles (aligned with Hermes xai-oauth + LiteLLM fallback chains):
  1. Grok Heavy subscription (Hermes xai-oauth / auth.json)
  2. OAuth refresh on auth failure (401/403)
  3. Paid xAI console API key (XAI_API_KEY / GROK_API_KEY) as durable fallback

All Grok HTTP callers in D:\\HermesData\\scripts should import from here.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

HERMES_ROOT = Path(r"D:\HermesData")
CONFIG_PATH = HERMES_ROOT / "config.yaml"
AUTH_LOG = Path(r"D:\PhronesisVault\Operations\logs\grok-auth.jsonl")
DEFAULT_BASE_URL = "https://api.x.ai/v1"

AUTH_OAUTH = "xai-oauth"
AUTH_API = "xai"
BILLING_SUBSCRIPTION = "grok_heavy_subscription"
BILLING_CONSOLE = "xai_console_api"

DEFAULT_OAUTH_FALLBACK_HTTP = frozenset({401, 403, 404})
DEFAULT_TRANSIENT_HTTP = frozenset({502, 503, 504})
DEFAULT_RATE_LIMIT_HTTP = frozenset({429})
AUTH_REFRESH_HTTP = frozenset({401, 403})

_POLICY_CACHE: Dict[str, Any] = {"loaded_at": 0.0, "policy": {}}
_POLICY_CACHE_TTL_SEC = 30.0
_RATE_LIMIT_UNTIL: Dict[str, float] = {}


def _log(event: Dict[str, Any]) -> None:
    try:
        AUTH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUTH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def bootstrap_hermes() -> None:
    try:
        scripts = HERMES_ROOT / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from phronesis_env import bootstrap_env

        bootstrap_env()
    except Exception:
        pass
    agent_root = HERMES_ROOT / "hermes-agent"
    if agent_root.is_dir() and str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def grok_auth_policy(config_path: Optional[Path] = None) -> Dict[str, Any]:
    now = time.time()
    cache_key = str(config_path or CONFIG_PATH)
    cached = _POLICY_CACHE.get("policy") or {}
    if (
        cached
        and _POLICY_CACHE.get("cache_key") == cache_key
        and (now - float(_POLICY_CACHE.get("loaded_at") or 0.0)) < _POLICY_CACHE_TTL_SEC
    ):
        return dict(cached)

    raw = _load_yaml(config_path or CONFIG_PATH)
    cfg = raw.get("grok_auth") or {}
    xs = raw.get("x_search") or {}
    fallback_codes = cfg.get("fallback_http_codes") or [401, 403, 404]
    try:
        oauth_fallback_http: Set[int] = {int(c) for c in fallback_codes}
    except Exception:
        oauth_fallback_http = set(DEFAULT_OAUTH_FALLBACK_HTTP)
    oauth_fallback_http -= DEFAULT_RATE_LIMIT_HTTP
    policy = {
        "prefer_subscription": bool(cfg.get("prefer_subscription", True)),
        "oauth_refresh_on_auth_fail": bool(cfg.get("oauth_refresh_on_auth_fail", True)),
        "oauth_fallback_http": oauth_fallback_http,
        "transient_retry": bool(cfg.get("transient_retry", True)),
        "rate_limit_retries": int(cfg.get("rate_limit_retries") or 2),
        "rate_limit_max_wait_sec": int(cfg.get("rate_limit_max_wait_sec") or 120),
        "timeout_seconds": int(cfg.get("timeout_seconds") or xs.get("timeout_seconds") or 180),
        "oauth_model": str(xs.get("oauth_model") or "grok-4.20-0309-reasoning"),
        "api_model": str(xs.get("model") or "grok-4.20-reasoning"),
    }
    _POLICY_CACHE["cache_key"] = cache_key
    _POLICY_CACHE["loaded_at"] = now
    _POLICY_CACHE["policy"] = policy
    return dict(policy)


def resolve_console_api_key() -> str:
    for name in ("XAI_API_KEY", "GROK_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val.split(" #", 1)[0].strip()
    bootstrap_hermes()
    try:
        from hermes_cli.config import get_env_value

        for name in ("XAI_API_KEY", "GROK_API_KEY"):
            val = str(get_env_value(name) or "").strip()
            if val:
                return val.split(" #", 1)[0].strip()
    except Exception:
        pass
    return ""


def resolve_grok_credentials(
    *,
    force_refresh: bool = False,
    force_api_key: bool = False,
) -> Dict[str, Any]:
    """Resolve one Grok credential set. OAuth first unless force_api_key."""
    bootstrap_hermes()
    if not force_api_key:
        try:
            from tools.xai_http import resolve_xai_http_credentials

            creds = resolve_xai_http_credentials(force_refresh=force_refresh)
            api_key = str(creds.get("api_key") or "").strip()
            provider = str(creds.get("provider") or "").strip() or AUTH_API
            base_url = str(creds.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
            if api_key and provider == AUTH_OAUTH:
                return {
                    "api_key": api_key,
                    "base_url": base_url,
                    "auth_provider": provider,
                    "billing": BILLING_SUBSCRIPTION,
                }
        except Exception as exc:
            _log({"event": "oauth_resolve_error", "error": str(exc)})

    api_key = resolve_console_api_key()
    if not api_key:
        return {}
    return {
        "api_key": api_key,
        "base_url": DEFAULT_BASE_URL,
        "auth_provider": AUTH_API,
        "billing": BILLING_CONSOLE,
    }


def plan_grok_auth_attempts() -> List[Dict[str, Any]]:
    """Ordered auth ladder: subscription OAuth -> console API (refresh is lazy on auth fail)."""
    pol = grok_auth_policy()
    oauth = resolve_grok_credentials() if pol.get("prefer_subscription") else {}
    api = resolve_grok_credentials(force_api_key=True)
    attempts: List[Dict[str, Any]] = []
    if oauth.get("api_key") and oauth.get("auth_provider") == AUTH_OAUTH:
        attempts.append(oauth)
    if api.get("api_key"):
        attempts.append(api)
    return attempts


def _auth_cooldown_key(auth: Dict[str, Any]) -> str:
    return str(auth.get("billing") or auth.get("auth_provider") or "unknown")


def _rate_limit_active(auth: Dict[str, Any]) -> bool:
    until = float(_RATE_LIMIT_UNTIL.get(_auth_cooldown_key(auth)) or 0.0)
    return until > time.time()


def _set_rate_limit_cooldown(auth: Dict[str, Any], wait_sec: float) -> float:
    wait = max(1.0, min(float(wait_sec), 600.0))
    _RATE_LIMIT_UNTIL[_auth_cooldown_key(auth)] = time.time() + wait
    return wait


def _parse_retry_after_sec(exc: urllib.error.HTTPError) -> Optional[float]:
    raw = (exc.headers.get("Retry-After") or exc.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def resolve_grok_model(
    auth_provider: str,
    *,
    override: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> str:
    if override:
        return override
    pol = grok_auth_policy(config_path)
    if auth_provider == AUTH_OAUTH:
        return str(pol.get("oauth_model") or "grok-4.20-0309-reasoning")
    return str(pol.get("api_model") or "grok-4.20-reasoning")


def _should_fallback_from_oauth(http_status: int, policy: Dict[str, Any]) -> bool:
    return http_status in set(policy.get("oauth_fallback_http") or DEFAULT_OAUTH_FALLBACK_HTTP)


def grok_chat_completion(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: Optional[int] = None,
    user_agent: str = "PhronesisGrok/1.0",
) -> Dict[str, Any]:
    """
    Chat completion with uniform auth ladder.

    Returns dict with success, response, model, provenance, openai_response, error, http_status.
    """
    pol = grok_auth_policy()
    req_timeout = int(timeout or pol.get("timeout_seconds") or 180)
    attempts = plan_grok_auth_attempts()
    if not attempts:
        return {
            "success": False,
            "error": "no_grok_credentials",
            "response": (
                "No Grok Heavy OAuth session and no XAI_API_KEY. "
                "Run `hermes auth add xai-oauth` or sync console key."
            ),
        }

    trail: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {"success": False, "error": "grok_dispatch_failed"}
    oauth_refreshed = False

    for auth in attempts:
        if _rate_limit_active(auth):
            trail.append({
                "billing": auth.get("billing"),
                "provider": auth.get("auth_provider"),
                "success": False,
                "skipped": "rate_limit_cooldown",
            })
            continue

        resolved_model = resolve_grok_model(
            str(auth.get("auth_provider") or AUTH_API),
            override=model,
        )
        result = _dispatch_with_retries(
            auth,
            resolved_model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=req_timeout,
            user_agent=user_agent,
            pol=pol,
        )
        trail.extend(result.get("trail") or [])
        result = {k: v for k, v in result.items() if k != "trail"}

        if result.get("success"):
            prov = result.setdefault("provenance", {})
            prov["auth_ladder"] = auth.get("billing")
            prov["auth_attempts"] = trail
            _log({"event": "grok_ok", "billing": auth.get("billing"), "model": resolved_model})
            return result

        http_status = int(result.get("http_status") or 0)
        last_result = result

        if (
            auth.get("auth_provider") == AUTH_OAUTH
            and pol.get("oauth_refresh_on_auth_fail")
            and http_status in AUTH_REFRESH_HTTP
            and not oauth_refreshed
        ):
            oauth_refreshed = True
            refreshed = resolve_grok_credentials(force_refresh=True)
            if refreshed.get("api_key") and refreshed.get("auth_provider") == AUTH_OAUTH:
                refresh_result = _dispatch_with_retries(
                    refreshed,
                    resolve_grok_model(AUTH_OAUTH, override=model),
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=req_timeout,
                    user_agent=user_agent,
                    pol=pol,
                )
                trail.extend(refresh_result.get("trail") or [])
                refresh_result = {k: v for k, v in refresh_result.items() if k != "trail"}
                if refresh_result.get("success"):
                    prov = refresh_result.setdefault("provenance", {})
                    prov["auth_ladder"] = refreshed.get("billing")
                    prov["auth_attempts"] = trail
                    _log({
                        "event": "grok_ok_oauth_refresh",
                        "billing": refreshed.get("billing"),
                        "model": resolve_grok_model(AUTH_OAUTH, override=model),
                    })
                    return refresh_result
                last_result = refresh_result
                http_status = int(refresh_result.get("http_status") or 0)

        if (
            auth.get("auth_provider") == AUTH_OAUTH
            and _should_fallback_from_oauth(http_status, pol)
        ):
            _log({
                "event": "grok_oauth_fallback",
                "http_status": http_status,
                "model": resolved_model,
            })
            continue

    last_result.setdefault("provenance", {})["auth_attempts"] = trail
    _log({"event": "grok_fail", "attempts": trail})
    return last_result


def _dispatch_with_retries(
    auth: Dict[str, Any],
    model: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: int,
    user_agent: str,
    pol: Dict[str, Any],
) -> Dict[str, Any]:
    trail: List[Dict[str, Any]] = []
    rate_retries = max(0, int(pol.get("rate_limit_retries") or 2))
    max_rate_wait = int(pol.get("rate_limit_max_wait_sec") or 120)

    for attempt in range(rate_retries + 1):
        result = _grok_http_post(
            auth,
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            user_agent=user_agent,
        )
        entry = {
            "billing": auth.get("billing"),
            "provider": auth.get("auth_provider"),
            "model": model,
            "success": bool(result.get("success")),
            "http_status": result.get("http_status"),
            "error": (str(result.get("error") or "")[:120] or None),
        }
        trail.append(entry)

        if result.get("success"):
            result["trail"] = trail
            return result

        http_status = int(result.get("http_status") or 0)

        if pol.get("transient_retry") and http_status in DEFAULT_TRANSIENT_HTTP:
            retry = _grok_http_post(
                auth,
                model,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                user_agent=user_agent,
            )
            trail.append({
                "billing": auth.get("billing"),
                "provider": auth.get("auth_provider"),
                "model": model,
                "success": bool(retry.get("success")),
                "http_status": retry.get("http_status"),
                "retry": "transient",
                "error": (str(retry.get("error") or "")[:120] or None),
            })
            if retry.get("success"):
                retry["trail"] = trail
                return retry
            result = retry
            http_status = int(result.get("http_status") or 0)

        if http_status not in DEFAULT_RATE_LIMIT_HTTP or attempt >= rate_retries:
            result["trail"] = trail
            return result

        wait_sec = float(result.get("retry_after_sec") or 30.0)
        wait_sec = _set_rate_limit_cooldown(auth, min(wait_sec, max_rate_wait))
        _log({
            "event": "grok_rate_limit_wait",
            "billing": auth.get("billing"),
            "wait_sec": wait_sec,
            "attempt": attempt + 1,
        })
        time.sleep(wait_sec)

    result["trail"] = trail
    return result


def grok_chat_completion_text(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: Optional[int] = None,
    user_agent: str = "PhronesisGrok/1.0",
) -> str:
    result = grok_chat_completion(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        user_agent=user_agent,
    )
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or result.get("response") or "grok_chat_failed"))
    content = str(result.get("response") or "").strip()
    if not content:
        raise RuntimeError("grok_chat_empty_content")
    return content


def grok_user_prompt_completion(
    prompt: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Single user-turn completion (T3 / proactive offload)."""
    return grok_chat_completion(
        [{"role": "user", "content": prompt[:120000]}],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )


def _grok_http_post(
    auth: Dict[str, Any],
    model: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: int,
    user_agent: str,
) -> Dict[str, Any]:
    url = f"{auth['base_url']}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    started = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth['api_key']}",
                "User-Agent": user_agent,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "").strip()
        if not content:
            raise RuntimeError("empty_grok_response")
        latency = round(time.time() - started, 2)
        return {
            "success": True,
            "response": content,
            "model": model,
            "tier": "paid_grok",
            "latency_sec": latency,
            "provenance": {
                "selected_backend": "paid_grok",
                "provider": auth.get("auth_provider") or AUTH_API,
                "billing": auth.get("billing") or BILLING_CONSOLE,
            },
            "openai_response": body,
        }
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        retry_after = _parse_retry_after_sec(exc)
        return {
            "success": False,
            "http_status": exc.code,
            "retry_after_sec": retry_after,
            "error": f"HTTP {exc.code}: {err_body[:200]}",
            "provenance": {
                "selected_backend": "paid_grok",
                "provider": auth.get("auth_provider") or AUTH_API,
                "billing": auth.get("billing"),
                "http_status": exc.code,
                "retry_after_sec": retry_after,
            },
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "provenance": {
                "selected_backend": "paid_grok",
                "provider": auth.get("auth_provider") or AUTH_API,
                "billing": auth.get("billing"),
                "error": str(exc),
            },
        }