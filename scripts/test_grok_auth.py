#!/usr/bin/env python3
"""Unit tests for uniform grok_auth ladder."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from grok_auth import (  # noqa: E402
    AUTH_OAUTH,
    grok_chat_completion,
    grok_auth_policy,
    plan_grok_auth_attempts,
    resolve_grok_credentials,
    resolve_grok_model,
)
from escalation_router import try_t3_paid_dispatch  # noqa: E402


def test_policy_defaults() -> None:
    pol = grok_auth_policy()
    assert pol.get("prefer_subscription") is True
    assert 403 in set(pol.get("oauth_fallback_http") or [])


def test_resolve_grok_model_oauth() -> None:
    assert resolve_grok_model(AUTH_OAUTH) == "grok-4.20-0309-reasoning"


def test_resolve_grok_model_api() -> None:
    assert resolve_grok_model("xai") == "grok-4.20-reasoning"


def test_oauth_preferred_over_api_key() -> None:
    fake_oauth = {
        "provider": "xai-oauth",
        "api_key": "oauth-token-abc",
        "base_url": "https://api.x.ai/v1",
    }
    with patch("tools.xai_http.resolve_xai_http_credentials", return_value=fake_oauth):
        creds = resolve_grok_credentials()
    assert creds.get("auth_provider") == "xai-oauth"
    assert creds.get("billing") == "grok_heavy_subscription"


def test_force_api_key_skips_oauth() -> None:
    with patch("tools.xai_http.resolve_xai_http_credentials") as mock_resolve:
        with patch("grok_auth.resolve_console_api_key", return_value="xai-console-key"):
            creds = resolve_grok_credentials(force_api_key=True)
    mock_resolve.assert_not_called()
    assert creds.get("auth_provider") == "xai"
    assert creds.get("billing") == "xai_console_api"


def test_plan_no_pre_refresh() -> None:
    oauth_auth = {
        "api_key": "oauth-token",
        "base_url": "https://api.x.ai/v1",
        "auth_provider": "xai-oauth",
        "billing": "grok_heavy_subscription",
    }
    api_auth = {
        "api_key": "xai-key",
        "base_url": "https://api.x.ai/v1",
        "auth_provider": "xai",
        "billing": "xai_console_api",
    }
    with patch("grok_auth.resolve_grok_credentials", side_effect=[oauth_auth, api_auth]) as mock_resolve:
        attempts = plan_grok_auth_attempts()
    assert len(attempts) == 2
    assert mock_resolve.call_count == 2
    assert not any(call.kwargs.get("force_refresh") for call in mock_resolve.call_args_list)


def test_grok_falls_back_to_api_on_oauth_403() -> None:
    oauth_auth = {
        "api_key": "oauth-token",
        "base_url": "https://api.x.ai/v1",
        "auth_provider": "xai-oauth",
        "billing": "grok_heavy_subscription",
    }
    refreshed_auth = {
        "api_key": "oauth-token-refreshed",
        "base_url": "https://api.x.ai/v1",
        "auth_provider": "xai-oauth",
        "billing": "grok_heavy_subscription",
    }
    api_auth = {
        "api_key": "xai-key",
        "base_url": "https://api.x.ai/v1",
        "auth_provider": "xai",
        "billing": "xai_console_api",
    }
    oauth_fail = {
        "success": False,
        "http_status": 403,
        "error": "HTTP 403",
    }
    api_ok = {
        "success": True,
        "response": "ok from api",
        "model": "grok-4.20-reasoning",
        "provenance": {"provider": "xai", "billing": "xai_console_api"},
    }

    with patch("grok_auth.plan_grok_auth_attempts", return_value=[oauth_auth, api_auth]):
        with patch("grok_auth.resolve_grok_credentials", return_value=refreshed_auth):
            with patch("grok_auth._grok_http_post", side_effect=[oauth_fail, oauth_fail, api_ok]):
                result = grok_chat_completion([{"role": "user", "content": "ping"}])

    assert result.get("success"), result
    assert result.get("response") == "ok from api"


def test_t3_uses_grok_auth() -> None:
    ok = {
        "success": True,
        "response": "t3 ok",
        "model": "grok-4.20-0309-reasoning",
        "provenance": {"billing": "grok_heavy_subscription"},
    }
    with patch("escalation_router.fleet_policy", return_value={"prefer_free_before_grok": False}):
        with patch("grok_auth.grok_user_prompt_completion", return_value=ok):
            result = try_t3_paid_dispatch("Explain system design.", {"task_type": "research"})
    assert result.get("success")
    assert result.get("response") == "t3 ok"


def main() -> int:
    tests = [
        test_policy_defaults,
        test_resolve_grok_model_oauth,
        test_resolve_grok_model_api,
        test_oauth_preferred_over_api_key,
        test_force_api_key_skips_oauth,
        test_plan_no_pre_refresh,
        test_grok_falls_back_to_api_on_oauth_403,
        test_t3_uses_grok_auth,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())