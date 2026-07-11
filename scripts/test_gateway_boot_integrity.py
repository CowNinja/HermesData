#!/usr/bin/env python3
"""Smoke: gateway boot integrity probe and gate wiring."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PY = Path(r"D:\HermesData\hermes-agent\venv\Scripts\python.exe")
SCRIPTS = Path(__file__).resolve().parent
HERMES_AGENT = SCRIPTS.parent / "hermes-agent"


def _run(script: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [str(PY), str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(SCRIPTS),
        env=merged,
    )


def test_boot_script_passes() -> None:
    proc = _run(SCRIPTS / "gateway_boot_integrity.py", "--mode", "fast", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("boot_probe") is True
    assert payload.get("ok") is True


def test_gate_module_passes_on_phronesis_host() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(HERMES_AGENT)!r})\n"
        "from pathlib import Path\n"
        "from gateway.phronesis_boot_integrity import run_boot_integrity_gate\n"
        "ok, lines = run_boot_integrity_gate(force=True)\n"
        "print('OK' if ok else 'FAIL')\n"
        "for ln in lines:\n"
        "    print(ln)\n"
        "raise SystemExit(0 if ok else 1)\n"
    )
    proc = subprocess.run([str(PY), "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout or "skipped" in proc.stdout.lower()


def test_gate_skips_when_disabled() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(HERMES_AGENT)!r})\n"
        "from gateway.phronesis_boot_integrity import run_boot_integrity_gate\n"
        "ok, lines = run_boot_integrity_gate()\n"
        "print(lines)\n"
        "raise SystemExit(0 if ok else 1)\n"
    )
    proc = subprocess.run(
        [str(PY), "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PHRONESIS_BOOT_INTEGRITY": "0"},
    )
    assert proc.returncode == 0
    assert any("skipped" in ln.lower() for ln in proc.stdout.splitlines())


def test_pass_marker_written() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(HERMES_AGENT)!r})\n"
        "from gateway.phronesis_boot_integrity import run_boot_integrity_gate\n"
        "run_boot_integrity_gate(force=True)\n"
    )
    subprocess.run([str(PY), "-c", code], check=False)
    marker = Path(r"D:\HermesData\gateway\.last_integrity_pass")
    assert marker.is_file(), "expected integrity pass marker"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload.get("ok") is True


def main() -> int:
    test_boot_script_passes()
    test_gate_module_passes_on_phronesis_host()
    test_gate_skips_when_disabled()
    test_pass_marker_written()
    print("PASSED gateway boot integrity tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())