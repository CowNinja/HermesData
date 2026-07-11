#!/usr/bin/env python3
"""Preflight gate: critical stack sources keep newlines, indentation, and shape.

Detects:
  - Total newline strip (classic oneline corruption)
  - Partial merge (absurd max line length / mean line length)
  - Indentation strip (Python/PS1 blocks flattened to column 0)
  - CR-only line endings (carriage return without line feed)
  - Drift vs stored baselines (line count collapse, indent ratio drop)

Exit 0 = pass; 1 = corrupt or missing critical file.
Refresh baselines after intentional edits:
  python validate_stack_source_integrity.py --write-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stack_integrity_lib import (
    AstSymbols,
    ast_symbols_from_tree,
    binary_hygiene_issues,
    rel_key,
    sha256_hex,
    symbol_drift_reason,
)

ROOT = Path(r"D:\HermesData")
BASELINE_PATH = Path(__file__).resolve().parent / "stack_source_baselines.json"

CRITICAL_REL = (
    "scripts/sovereign_openai_proxy.py",
    "scripts/router_bridge.py",
    "scripts/ensure_hermes_sovereign_config.py",
    "scripts/validate_hermes_stack_config.py",
    "scripts/Start-Sovereign-Proxy-8091.ps1",
    "scripts/Phronesis-ForkGuard.ps1",
    "scripts/purge_expired_compression_locks.py",
    "scripts/ops/07-stack-preflight.ps1",
    "hermes-agent/agent/error_classifier.py",
    "hermes-agent/agent/chat_completion_helpers.py",
)

MIN_NEWLINES = {".py": 8, ".ps1": 5}
MIN_BYTES = 200
MAX_LINE_HARD = 2500
MAX_LINE_REL_FACTOR = 8
MAX_LINE_REL_MIN = 80
MEAN_LINE_HARD = 600
MIN_INDENT_RATIO = {".py": 0.06, ".ps1": 0.04}
MIN_NEWLINES_PER_KB = 1.5
BASELINE_LINE_RATIO = 0.75
BASELINE_INDENT_DROP = 0.20
BASELINE_MAX_LINE_SLACK = 400
BASELINE_SYMBOL_RATIO = 0.80


@dataclass
class FileMetrics:
    bytes: int
    newlines: int
    lines: int
    max_line_len: int
    median_line_len: float
    mean_line_len: float
    indent_ratio: float
    crlf: int
    lf_only: int
    cr_only: int
    newline_per_kb: float
    sha256: str = ""
    functions: int = 0
    classes: int = 0
    async_functions: int = 0


@dataclass
class CheckResult:
    path: str
    ok: bool
    newlines: int
    bytes: int
    reason: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)


def _line_ending_counts(raw: bytes) -> Tuple[int, int, int]:
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n")
    cr = raw.count(b"\r")
    cr_only = max(0, cr - crlf)
    lf_only = max(0, lf - crlf)
    return crlf, lf_only, cr_only


def _indent_ratio(lines: Sequence[str]) -> float:
    substantive = [
        ln
        for ln in lines
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if not substantive:
        return 0.0
    indented = sum(1 for ln in substantive if ln.startswith((" ", "\t")))
    return indented / len(substantive)


def _measure(raw: bytes, text: str) -> FileMetrics:
    lines = text.splitlines()
    line_lens = [len(ln) for ln in lines] or [0]
    sorted_lens = sorted(line_lens)
    mid = len(sorted_lens) // 2
    if len(sorted_lens) % 2:
        median = float(sorted_lens[mid])
    else:
        median = (sorted_lens[mid - 1] + sorted_lens[mid]) / 2.0
    crlf, lf_only, cr_only = _line_ending_counts(raw)
    size = len(raw)
    nl = raw.count(b"\n")
    return FileMetrics(
        bytes=size,
        newlines=nl,
        lines=len(lines),
        max_line_len=max(line_lens),
        median_line_len=median,
        mean_line_len=sum(line_lens) / len(line_lens),
        indent_ratio=_indent_ratio(lines),
        crlf=crlf,
        lf_only=lf_only,
        cr_only=cr_only,
        newline_per_kb=(nl / size * 1024) if size else 0.0,
    )


def _enrich_metrics(
    raw: bytes,
    m: FileMetrics,
    *,
    symbols: Optional[AstSymbols] = None,
) -> FileMetrics:
    m.sha256 = sha256_hex(raw)
    if symbols is not None:
        m.functions = symbols.functions
        m.classes = symbols.classes
        m.async_functions = symbols.async_functions
    return m


def _metrics_dict(m: FileMetrics) -> Dict[str, Any]:
    return asdict(m)


def _check_against_baseline(
    key: str,
    m: FileMetrics,
    baseline: Dict[str, Any],
) -> Optional[str]:
    base = baseline.get(key)
    if not base:
        return None
    base_lines = int(base.get("lines", 0))
    base_indent = float(base.get("indent_ratio", 0))
    base_max = int(base.get("max_line_len", 0))

    if base_lines >= 50 and m.lines < int(base_lines * BASELINE_LINE_RATIO):
        return (
            f"line count collapsed {m.lines} < {int(base_lines * BASELINE_LINE_RATIO)} "
            f"(baseline {base_lines})"
        )
    if base_max > 0 and m.max_line_len > base_max + BASELINE_MAX_LINE_SLACK:
        return (
            f"max line grew {m.max_line_len} > baseline {base_max}+{BASELINE_MAX_LINE_SLACK} "
            "(partial merge suspect)"
        )
    if base_indent >= 0.15 and m.indent_ratio < base_indent - BASELINE_INDENT_DROP:
        return (
            f"indent ratio dropped {m.indent_ratio:.3f} vs baseline {base_indent:.3f} "
            "(whitespace/indent clip suspect)"
        )
    sym_reason = symbol_drift_reason(
        AstSymbols(m.functions, m.classes, m.async_functions),
        base,
        min_ratio=BASELINE_SYMBOL_RATIO,
    )
    if sym_reason:
        return sym_reason
    return None


def _check_file(
    path: Path,
    baseline: Optional[Dict[str, Any]] = None,
    use_baseline: bool = True,
) -> CheckResult:
    rel = str(path)
    key = rel_key(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return CheckResult(rel, False, 0, 0, f"unreadable: {exc}")

    suffix = path.suffix.lower()
    for issue in binary_hygiene_issues(raw):
        return CheckResult(rel, False, raw.count(b"\n"), len(raw), issue)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return CheckResult(rel, False, raw.count(b"\n"), len(raw), f"utf-8 decode failed: {exc}")

    m = _enrich_metrics(raw, _measure(raw, text))
    md = _metrics_dict(m)

    if m.bytes < MIN_BYTES:
        return CheckResult(rel, False, m.newlines, m.bytes, f"too small ({m.bytes} bytes)", md)

    min_nl = MIN_NEWLINES.get(suffix, 3)
    if m.newlines < min_nl:
        return CheckResult(
            rel, False, m.newlines, m.bytes,
            f"newlines={m.newlines} < min {min_nl} (CR/LF stripped)",
            md,
        )

    if m.cr_only > 0 and m.cr_only >= m.crlf + m.lf_only:
        return CheckResult(
            rel, False, m.newlines, m.bytes,
            f"CR-only line endings dominate (cr_only={m.cr_only})",
            md,
        )

    rel_max_cap = max(MAX_LINE_REL_MIN, int(m.median_line_len * MAX_LINE_REL_FACTOR))
    merged_suspect = m.lines >= 12 and m.max_line_len > rel_max_cap
    if m.max_line_len > MAX_LINE_HARD or merged_suspect:
        cap = MAX_LINE_HARD if m.max_line_len > MAX_LINE_HARD else rel_max_cap
        return CheckResult(
            rel, False, m.newlines, m.bytes,
            f"max_line_len={m.max_line_len} > cap {cap} (lines merged)",
            md,
        )

    if m.bytes >= 1500 and m.mean_line_len > MEAN_LINE_HARD:
        return CheckResult(
            rel, False, m.newlines, m.bytes,
            f"mean_line_len={m.mean_line_len:.0f} > {MEAN_LINE_HARD} (structure flattened)",
            md,
        )

    min_indent = MIN_INDENT_RATIO.get(suffix, 0.03)
    if m.bytes >= 800 and m.indent_ratio < min_indent:
        return CheckResult(
            rel, False, m.newlines, m.bytes,
            f"indent_ratio={m.indent_ratio:.3f} < {min_indent} (indent stripped)",
            md,
        )

    if m.bytes >= 2048 and m.newline_per_kb < MIN_NEWLINES_PER_KB:
        return CheckResult(
            rel, False, m.newlines, m.bytes,
            f"newline_density={m.newline_per_kb:.2f}/KB < {MIN_NEWLINES_PER_KB}",
            md,
        )

    if suffix == ".py":
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            return CheckResult(rel, False, m.newlines, m.bytes, f"syntax error: {exc}", md)
        m = _enrich_metrics(raw, m, symbols=ast_symbols_from_tree(tree))
        md = _metrics_dict(m)
        body = [n for n in tree.body if not isinstance(n, ast.Expr)]
        if not body:
            return CheckResult(
                rel, False, m.newlines, m.bytes,
                "AST body empty (docstring-only oneline)",
                md,
            )

    if use_baseline and baseline is not None:
        drift = _check_against_baseline(key, m, baseline)
        if drift:
            return CheckResult(rel, False, m.newlines, m.bytes, drift, md)

    return CheckResult(rel, True, m.newlines, m.bytes, "", md)


def _load_baseline() -> Dict[str, Any]:
    if not BASELINE_PATH.is_file():
        return {}
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        return data.get("files", data) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_baseline(paths: Sequence[Path]) -> Dict[str, Any]:
    files: Dict[str, Any] = {}
    for path in paths:
        if not path.is_file():
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        m = _measure(raw, text)
        key = rel_key(path)
        if path.suffix.lower() == ".py":
            tree = ast.parse(text, filename=str(path))
            m = _enrich_metrics(raw, m, symbols=ast_symbols_from_tree(tree))
        else:
            m = _enrich_metrics(raw, m)
        files[key] = _metrics_dict(m)
    payload = {
        "version": 2,
        "root": str(ROOT),
        "files": files,
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def resolve_paths(extra: Optional[Sequence[str]] = None) -> List[Path]:
    if extra:
        return [Path(p).resolve() for p in extra]
    return [(ROOT / rel).resolve() for rel in CRITICAL_REL]


def run_checks(
    paths: Sequence[Path],
    baseline: Optional[Dict[str, Any]] = None,
    use_baseline: bool = True,
) -> List[CheckResult]:
    return [_check_file(p, baseline=baseline, use_baseline=use_baseline) for p in paths]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Critical stack source structure gate")
    ap.add_argument("--json", action="store_true", help="JSON report on stdout")
    ap.add_argument("--paths", nargs="+", help="Override file list (skips baseline drift)")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="Snapshot current metrics to stack_source_baselines.json",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    paths = resolve_paths(args.paths)
    use_baseline = not args.paths

    if args.write_baseline:
        payload = _write_baseline([p for p in paths if p.is_file()])
        print(f"Wrote baseline for {len(payload['files'])} files -> {BASELINE_PATH}")
        return 0

    baseline = _load_baseline() if use_baseline else None
    missing = [p for p in paths if not p.is_file()]
    results = run_checks([p for p in paths if p.is_file()], baseline=baseline, use_baseline=use_baseline)

    for p in missing:
        results.append(CheckResult(str(p), False, 0, 0, "missing file"))

    fails = [r for r in results if not r.ok]
    payload = {
        "ok": len(fails) == 0,
        "checked": len(results),
        "failures": len(fails),
        "baseline": str(BASELINE_PATH) if use_baseline else None,
        "results": [asdict(r) for r in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        if fails:
            print(f"FAIL: {len(fails)} critical source(s) corrupt or drifted")
            for r in fails:
                print(f"  {r.path}: {r.reason}")
        else:
            print(
                f"OK: {len(results)} critical stack sources passed "
                "(newlines, indent, line shape, baseline)"
            )

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())