#!/usr/bin/env python3
"""Normalize executable scripts to 7-bit ASCII (printable + tab/newline)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPLACEMENTS: list[tuple[str, str]] = [
    ("\u2014", "-"),   # em dash
    ("\u2013", "-"),   # en dash
    ("\u2212", "-"),   # minus
    ("\u2192", "->"),
    ("\u2190", "<-"),
    ("\u2191", "^"),
    ("\u2193", "v"),
    ("\u2713", "[OK]"),
    ("\u2714", "[OK]"),
    ("\u2717", "[FAIL]"),
    ("\u2718", "[FAIL]"),
    ("\u26a0\ufe0f", "[WARN]"),
    ("\u26a0", "[WARN]"),
    ("\u2026", "..."),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u00ab", "<<"),
    ("\u00bb", ">>"),
    ("\u00a0", " "),
    ("\ufeff", ""),
]

BOX_TRANSLATE = str.maketrans(
    {
        "\u250c": "+",
        "\u2510": "+",
        "\u2514": "+",
        "\u2518": "+",
        "\u251c": "+",
        "\u2524": "+",
        "\u252c": "+",
        "\u2534": "+",
        "\u253c": "+",
        "\u2550": "=",
        "\u2551": "|",
        "\u2554": "+",
        "\u2557": "+",
        "\u255a": "+",
        "\u255d": "+",
        "\u2560": "+",
        "\u2563": "+",
        "\u2566": "+",
        "\u2569": "+",
        "\u256c": "+",
        "\u2500": "-",
        "\u2502": "|",
    }
)

# Common emoji / symbols in vendor shell scripts
EMOJI_TRANSLATE = str.maketrans(
    {
        "\U0001f680": "[rocket]",
        "\U0001f4e6": "[package]",
        "\U0001f4c1": "[folder]",
        "\U0001f50d": "[search]",
        "\U0001f3af": "[target]",
        "\U0001f6a8": "[alert]",
        "\u2705": "[OK]",
        "\u274c": "[FAIL]",
        "\u2728": "*",
        "\u00e9": "e",
        "\u00e8": "e",
        "\u00ec": "i",
        "\u00f1": "n",
    }
)


def detect_newline(raw: bytes) -> str:
    return "\r\n" if b"\r\n" in raw else "\n"


def to_ascii(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    text = text.translate(BOX_TRANSLATE)
    text = text.translate(EMOJI_TRANSLATE)
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        if ch in "\t\n\r" or 32 <= o <= 126:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def repair_file(path: Path, *, dry_run: bool = False) -> tuple[str, int]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    newline = detect_newline(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    repaired = to_ascii(text)
    if newline == "\r\n":
        repaired = repaired.replace("\n", "\r\n").replace("\r\r\n", "\r\n")
    # HARD GUARD: never flatten multi-line sources (2026-07-09 zero-newline incident)
    src_nl = raw.count(b"\n")
    out_bytes = repaired.encode("ascii")
    out_nl = out_bytes.count(b"\n")
    if src_nl > 0 and out_nl == 0:
        raise RuntimeError(
            f"newline integrity refused for {path}: source had {src_nl} LF, "
            "repair would write 0 (would create zero-newline corruption)"
        )
    if src_nl >= 5 and out_nl < max(1, src_nl // 10):
        raise RuntimeError(
            f"newline integrity refused for {path}: source LF={src_nl} out LF={out_nl} "
            "(suspiciously collapsed)"
        )
    non_ascii_before = sum(1 for b in raw if b not in (9, 10, 13) and (b < 32 or b > 126))
    if out_bytes == raw:
        return "ok", 0
    if dry_run:
        return "would_fix", non_ascii_before
    path.write_bytes(out_bytes)
    return "fixed", non_ascii_before


def collect_script_files(roots: list[Path], extensions: set[str]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix.lower() in extensions:
                found.append(root)
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions:
                found.append(path)
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="Explicit files to repair")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="Directories to scan recursively (e.g. D:\\HermesData\\scripts)",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=[".ps1", ".bat", ".cmd", ".vbs", ".sh"],
        help="Extensions to repair when using --paths",
    )
    parser.add_argument("--from-lint", action="store_true", help="Read FAIL paths from stdin lint output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files: list[Path] = [Path(f) for f in args.files]
    if args.paths:
        ext_set = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.extensions}
        files.extend(collect_script_files([Path(p) for p in args.paths], ext_set))
    if args.from_lint:
        for line in sys.stdin:
            line = line.strip()
            if line.startswith("D:\\") or line.startswith("D:/"):
                files.append(Path(line.split(" (", 1)[0].strip()))

    if not files:
        print("No files specified", file=sys.stderr)
        return 2

    fixed = ok = failed = 0
    for path in files:
        if not path.is_file():
            print(f"SKIP missing: {path}")
            failed += 1
            continue
        try:
            status, _ = repair_file(path, dry_run=args.dry_run)
            if status == "fixed":
                print(f"FIXED: {path}")
                fixed += 1
            elif status == "would_fix":
                print(f"DRY-RUN: {path}")
                fixed += 1
            else:
                print(f"OK: {path}")
                ok += 1
        except Exception as exc:
            print(f"ERROR {path}: {exc}", file=sys.stderr)
            failed += 1

    print(f"\nSummary: fixed={fixed} ok={ok} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())