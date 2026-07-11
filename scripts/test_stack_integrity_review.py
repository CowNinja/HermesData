#!/usr/bin/env python3
"""Smoke: full systematic stack integrity review passes on live tree."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
REVIEW = Path(__file__).resolve().parent / "stack_integrity_review.py"
VALIDATE = Path(__file__).resolve().parent / "validate_stack_source_integrity.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PY), str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(script.parent),
    )


def test_full_review_passes() -> None:
    proc = _run(REVIEW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


def test_fast_review_passes() -> None:
    proc = _run(REVIEW, "--fast")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_review_json_layers() -> None:
    proc = _run(REVIEW, "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    names = {layer["layer"] for layer in payload["layers"]}
    assert "structure" in names
    assert "compile" in names
    assert "import_smoke" in names
    assert "ops_scan" in names


def test_baseline_has_symbols_and_hash() -> None:
    proc = _run(VALIDATE, "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    proxy = next(
        r for r in payload["results"]
        if "sovereign_openai_proxy.py" in r["path"]
    )
    metrics = proxy["metrics"]
    assert metrics.get("sha256")
    assert metrics.get("functions", 0) > 10


def main() -> int:
    test_full_review_passes()
    test_fast_review_passes()
    test_review_json_layers()
    test_baseline_has_symbols_and_hash()
    print("PASSED stack integrity review tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())