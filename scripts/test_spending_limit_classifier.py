#!/usr/bin/env python3
"""Smoke: xAI spending-limit 403 classifies as billing, not auth."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hermes-agent"
sys.path.insert(0, str(ROOT))

from agent.error_classifier import FailoverReason, classify_api_error  # noqa: E402


class MockAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body or {}


def main() -> int:
    err = MockAPIError("personal-team-blocked:spending-limit", status_code=403)
    result = classify_api_error(err, provider="xai-oauth")
    assert result.reason == FailoverReason.billing, result.reason
    assert result.should_fallback is True
    print("PASSED billing classification for spending-limit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())