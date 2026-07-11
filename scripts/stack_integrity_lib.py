#!/usr/bin/env python3
"""Shared helpers for stack source integrity and systematic review."""
from __future__ import annotations

import ast
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(r"D:\HermesData")
SCRIPTS = ROOT / "scripts"


@dataclass
class AstSymbols:
    functions: int
    classes: int
    async_functions: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "functions": self.functions,
            "classes": self.classes,
            "async_functions": self.async_functions,
        }


def rel_key(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ast_symbols_from_tree(tree: ast.AST) -> AstSymbols:
    funcs = 0
    classes = 0
    async_funcs = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, ast.AsyncFunctionDef):
            async_funcs += 1
            funcs += 1
        elif isinstance(node, ast.FunctionDef):
            funcs += 1
    return AstSymbols(functions=funcs, classes=classes, async_functions=async_funcs)


def ast_symbols(text: str, filename: str = "<source>") -> AstSymbols:
    return ast_symbols_from_tree(ast.parse(text, filename=filename))


def binary_hygiene_issues(raw: bytes) -> List[str]:
    issues: List[str] = []
    if b"\x00" in raw:
        issues.append("contains null bytes")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        issues.append("UTF-16 BOM detected (expected UTF-8)")
    return issues


def bracket_balance_issues(text: str) -> List[str]:
    """Rough delimiter balance outside simple string literals."""
    stack: List[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    openers = set(pairs.values())
    in_str: Optional[str] = None
    escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            continue
        if ch in openers:
            stack.append(ch)
            continue
        if ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return [f"unbalanced delimiter near '{ch}'"]
            stack.pop()
    if stack:
        return [f"unclosed '{stack[-1]}'"]
    return []


def py_compile_ok(path: Path, python_exe: Path) -> Tuple[bool, str]:
    proc = subprocess.run(
        [str(python_exe), "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or proc.stdout or "py_compile failed").strip()
    return False, err[:300]


def powershell_parse_ok(path: Path) -> Tuple[bool, str]:
    ps = (
        "$tokens=$null; $errs=$null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}', "
        "[ref]$tokens, [ref]$errs); "
        "if ($errs) { $errs | ForEach-Object { $_.ToString() }; exit 1 } else { exit 0 }"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or proc.stdout or "powershell parse failed").strip()
    return False, err[:300]


def import_symbol_ok(
    module_name: str,
    symbol: str,
    path_hint: Path,
    python_exe: Path,
) -> Tuple[bool, str]:
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(path_hint.parent)!r})\n"
        f"m = importlib.import_module({module_name!r})\n"
        f"getattr(m, {symbol!r})\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [str(python_exe), "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(path_hint.parent),
    )
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or proc.stdout or "import failed").strip()
    return False, err[:400]


def scan_zero_newline(
    directory: Path,
    min_bytes: int = 400,
    suffixes: Sequence[str] = (".py", ".ps1"),
) -> List[Path]:
    bad: List[Path] = []
    if not directory.is_dir():
        return bad
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        if ".bak" in path.name.lower():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) >= min_bytes and raw.count(b"\n") == 0:
            bad.append(path)
    return bad


def symbol_drift_reason(
    current: AstSymbols,
    baseline: Dict[str, Any],
    *,
    min_ratio: float = 0.80,
) -> Optional[str]:
    base_funcs = int(baseline.get("functions", 0))
    base_classes = int(baseline.get("classes", 0))
    if base_funcs >= 5 and current.functions < int(base_funcs * min_ratio):
        return (
            f"function count collapsed {current.functions} < "
            f"{int(base_funcs * min_ratio)} (baseline {base_funcs})"
        )
    if base_classes >= 2 and current.classes < max(1, int(base_classes * min_ratio)):
        return (
            f"class count collapsed {current.classes} < "
            f"{int(base_classes * min_ratio)} (baseline {base_classes})"
        )
    return None