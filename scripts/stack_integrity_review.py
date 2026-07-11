#!/usr/bin/env python3
"""Systematic stack source integrity review (layered corruption detection).

Layers:
  1. structure   - newlines, indent, line shape, baseline drift (validate_stack_source_integrity)
  2. compile     - py_compile on critical Python modules
  3. parse_ps1   - PowerShell parser on critical launch/ops scripts
  4. import_smoke- import critical symbols (proxy/router/classifier wiring)
  5. ops_scan    - zero-newline detection under scripts/ops (known corruption zone)

Usage:
  python stack_integrity_review.py            # full review
  python stack_integrity_review.py --fast     # structure only
  python stack_integrity_review.py --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from stack_integrity_lib import (
    ROOT,
    SCRIPTS,
    import_symbol_ok,
    powershell_parse_ok,
    py_compile_ok,
    rel_key,
    scan_zero_newline,
)

VENV_PY = ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe"
VALIDATE = SCRIPTS / "validate_stack_source_integrity.py"

CRITICAL_PY = (
    "scripts/sovereign_openai_proxy.py",
    "scripts/router_bridge.py",
    "scripts/ensure_hermes_sovereign_config.py",
    "scripts/validate_hermes_stack_config.py",
    "scripts/purge_expired_compression_locks.py",
    "hermes-agent/agent/error_classifier.py",
    "hermes-agent/agent/chat_completion_helpers.py",
)

CRITICAL_PS1 = (
    "scripts/Start-Sovereign-Proxy-8091.ps1",
    "scripts/Phronesis-ForkGuard.ps1",
    "scripts/ops/07-stack-preflight.ps1",
)

IMPORT_SMOKE = (
    (SCRIPTS, "sovereign_openai_proxy", "_flatten_tool_history_for_llama"),
    (SCRIPTS, "router_bridge", "preview_route"),
    (SCRIPTS, "validate_hermes_stack_config", "main"),
    (ROOT / "hermes-agent", "agent.error_classifier", "classify_api_error"),
)


@dataclass
class LayerResult:
    layer: str
    ok: bool
    detail: str = ""
    items: List[Dict[str, Any]] = field(default_factory=list)


def _run_structure() -> LayerResult:
    proc = subprocess.run(
        [str(VENV_PY), str(VALIDATE)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(SCRIPTS),
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return LayerResult("structure", proc.returncode == 0, out)


def _run_compile() -> LayerResult:
    items: List[Dict[str, Any]] = []
    ok = True
    for rel in CRITICAL_PY:
        path = (ROOT / rel).resolve()
        if not path.is_file():
            items.append({"path": rel, "ok": False, "error": "missing"})
            ok = False
            continue
        passed, err = py_compile_ok(path, VENV_PY)
        items.append({"path": rel, "ok": passed, "error": err})
        ok = ok and passed
    detail = f"{sum(1 for i in items if i['ok'])}/{len(items)} py_compile ok"
    return LayerResult("compile", ok, detail, items)


def _run_parse_ps1() -> LayerResult:
    items: List[Dict[str, Any]] = []
    ok = True
    for rel in CRITICAL_PS1:
        path = (ROOT / rel).resolve()
        if not path.is_file():
            items.append({"path": rel, "ok": False, "error": "missing"})
            ok = False
            continue
        passed, err = powershell_parse_ok(path)
        items.append({"path": rel, "ok": passed, "error": err})
        ok = ok and passed
    detail = f"{sum(1 for i in items if i['ok'])}/{len(items)} powershell parse ok"
    return LayerResult("parse_ps1", ok, detail, items)


def _run_import_smoke() -> LayerResult:
    items: List[Dict[str, Any]] = []
    ok = True
    for base, module, symbol in IMPORT_SMOKE:
        if module.startswith("agent."):
            path_hint = base / "agent" / "error_classifier.py"
            mod = module
            sys_path_parent = str(base)
            code_mod = mod
            proc = subprocess.run(
                [
                    str(VENV_PY),
                    "-c",
                    (
                        "import importlib, sys\n"
                        f"sys.path.insert(0, {sys_path_parent!r})\n"
                        f"getattr(importlib.import_module({code_mod!r}), {symbol!r})\n"
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(base),
            )
            passed = proc.returncode == 0
            err = (proc.stderr or proc.stdout or "").strip()[:400]
        else:
            path_hint = base / f"{module}.py"
            passed, err = import_symbol_ok(module, symbol, path_hint, VENV_PY)
        label = f"{module}.{symbol}"
        items.append({"symbol": label, "ok": passed, "error": err})
        ok = ok and passed
    detail = f"{sum(1 for i in items if i['ok'])}/{len(items)} import smoke ok"
    return LayerResult("import_smoke", ok, detail, items)


def _run_ops_scan() -> LayerResult:
    bad = scan_zero_newline(SCRIPTS / "ops", min_bytes=400)
    items = [{"path": rel_key(p), "bytes": p.stat().st_size} for p in bad]
    detail = f"{len(bad)} zero-newline file(s) under scripts/ops"
    return LayerResult("ops_scan", len(bad) == 0, detail, items)


def run_review(fast: bool = False) -> Dict[str, Any]:
    layers: List[LayerResult] = [_run_structure()]
    if not fast:
        layers.extend([
            _run_compile(),
            _run_parse_ps1(),
            _run_import_smoke(),
            _run_ops_scan(),
        ])
    ok = all(layer.ok for layer in layers)
    return {
        "ok": ok,
        "mode": "fast" if fast else "full",
        "layers": [asdict(layer) for layer in layers],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Systematic stack integrity review")
    ap.add_argument("--fast", action="store_true", help="Structure gate only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    report = run_review(fast=args.fast)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Stack integrity review ({report['mode']}): ", end="")
        if report["ok"]:
            print("PASS")
        else:
            print("FAIL")
        for layer in report["layers"]:
            mark = "OK" if layer["ok"] else "FAIL"
            print(f"  [{mark}] {layer['layer']}: {layer['detail']}")
            if not layer["ok"]:
                for item in layer.get("items", [])[:8]:
                    err = item.get("error") or item.get("path") or item.get("symbol")
                    print(f"       - {err}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())