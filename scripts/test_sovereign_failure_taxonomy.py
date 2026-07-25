#!/usr/bin/env python3
"""Phase 1 verification: 400 permanent must not map to retriable 503."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sovereign_failure_taxonomy import (  # noqa: E402
    CAPACITY,
    PERMANENT,
    TRANSIENT,
    classify_dispatch_failure,
    classify_exception_message,
    classify_http_status,
    http_status_for_failure_class,
)


def test_template_call_expression_permanent() -> None:
    msg = (
        "Unable to generate parser for this template. "
        "CallExpression at line 85, column 32"
    )
    assert classify_exception_message(msg) == PERMANENT
    d = classify_dispatch_failure(msg)
    assert d["failure_class"] == PERMANENT
    assert d["http_status"] == 400
    assert d["retryable"] is False
    assert d["error_type"] == "invalid_request_error"


def test_http_400_permanent() -> None:
    d = classify_dispatch_failure("upstream returned HTTP 400: bad request")
    assert d["failure_class"] == PERMANENT
    assert d["http_status"] == 400
    assert d["retryable"] is False


def test_connection_refused_transient() -> None:
    d = classify_dispatch_failure("Connection refused")
    assert d["failure_class"] == TRANSIENT
    assert d["http_status"] == 503
    assert d["retryable"] is True


def test_fifo_capacity() -> None:
    d = classify_dispatch_failure("FIFO at capacity")
    assert d["failure_class"] == CAPACITY
    assert d["http_status"] == 429


def test_disguised_503_with_template_body() -> None:
    # Upstream wrapped permanent as 503 in status but body says template
    cls = classify_http_status(
        503,
        "Unable to generate parser for this template CallExpression",
    )
    assert cls == PERMANENT
    assert http_status_for_failure_class(cls) == 400


def test_true_503_stays_transient() -> None:
    cls = classify_http_status(503, "Service Unavailable")
    assert cls == TRANSIENT
    assert http_status_for_failure_class(cls) == 503


def main() -> int:
    tests = [
        test_template_call_expression_permanent,
        test_http_400_permanent,
        test_connection_refused_transient,
        test_fifo_capacity,
        test_disguised_503_with_template_body,
        test_true_503_stays_transient,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
