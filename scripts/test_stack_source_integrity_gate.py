#!/usr/bin/env python3
"""Smoke: structure gate passes live files; fails oneline, dedent, and merge."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "validate_stack_source_integrity.py"
PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
SAMPLE = Path(r"D:\HermesData\scripts\purge_expired_compression_locks.py")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PY), str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_live_critical_paths_pass() -> None:
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout


def test_oneline_temp_file_fails() -> None:
    blob = (
        '#!/usr/bin/env python3\n"""fake module"""\n'
        + "import os\n" * 20
    ).replace("\n", " ")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(blob)
        bad = fh.name
    try:
        proc = _run("--paths", bad)
        assert proc.returncode != 0, "expected oneline temp to fail gate"
        assert "newlines=0" in proc.stdout or "lines merged" in proc.stdout
    finally:
        Path(bad).unlink(missing_ok=True)


def test_dedent_clip_fails() -> None:
    """Simulate indentation/leading-whitespace strip while keeping newlines."""
    text = SAMPLE.read_text(encoding="utf-8")
    dedented = "\n".join(line.lstrip() for line in text.splitlines()) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(dedented)
        bad = fh.name
    try:
        proc = _run("--paths", bad)
        combined = (proc.stdout + proc.stderr).lower()
        assert proc.returncode != 0, combined
        assert "indent" in combined or "syntax" in combined
    finally:
        Path(bad).unlink(missing_ok=True)


def test_partial_line_merge_fails() -> None:
    """Simulate partial CR/LF clip: many short lines joined into one long line."""
    lines = [f"x_{i} = {i}" for i in range(60)]
    lines[10] = " ".join(lines[10:35])
    del lines[11:35]
    blob = "\n".join(lines) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(blob)
        bad = fh.name
    try:
        proc = _run("--paths", bad)
        assert proc.returncode != 0, proc.stdout + proc.stderr
        low = proc.stdout.lower()
        assert any(
            token in low
            for token in ("merged", "max_line", "newlines=", "flattened", "indent")
        )
    finally:
        Path(bad).unlink(missing_ok=True)


def test_json_mode() -> None:
    proc = _run("--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("ok") is True
    assert payload.get("failures") == 0
    first = payload["results"][0]
    assert "metrics" in first
    assert "indent_ratio" in first["metrics"]
    assert "crlf" in first["metrics"]


def main() -> int:
    test_live_critical_paths_pass()
    test_oneline_temp_file_fails()
    test_dedent_clip_fails()
    test_partial_line_merge_fails()
    test_json_mode()
    print("PASSED stack source integrity gate tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())