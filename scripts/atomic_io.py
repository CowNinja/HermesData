#!/usr/bin/env python3
"""Shared atomic publish helpers for kitchen receipts.

Research / sources (2026-07-19 overnight):
- Python os.replace — atomic on same volume (POSIX rename; Windows ReplaceFile).
- Prior jan_unified incident: open(target, "w") truncated mid-build → 0-byte SSOT.
- Local parity: jan_unified_index._atomic_write_jsonl, vaultwalker._atomic_write_text,
  sovereign_ops_pulse._atomic_write_text, single_gateway tmp.replace.

Contract:
  write complete .tmp → flush/fsync → os.replace(tmp, target)
  On Windows lock (PermissionError/OSError): copy2 over target only AFTER tmp is complete.
  Never open(target, "w") first. Refuse tiny publishes when min_bytes set.
  Returns method string for forensics ("os.replace" | "copy2_fallback").
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, content: str, *, min_bytes: int = 1) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = content if content.endswith("\n") else content + "\n"
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    size = tmp.stat().st_size
    if size < int(min_bytes):
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError(f"refusing tiny atomic publish size={size} path={path}")

    method = "os.replace"
    try:
        os.replace(tmp, path)
    except OSError:
        method = "copy2_fallback"
        shutil.copy2(tmp, path)
        try:
            tmp.unlink()
        except OSError:
            pass

    try:
        if path.stat().st_size < int(min_bytes):
            raise RuntimeError(f"post-publish size too small: {path.stat().st_size} path={path}")
    except OSError as e:
        raise RuntimeError(f"post-publish stat failed path={path}: {e}") from e
    return method


def atomic_write_json(
    path: str | Path,
    obj: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    min_bytes: int = 20,
) -> str:
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)
    if not text.endswith("\n"):
        text += "\n"
    return atomic_write_text(path, text, min_bytes=min_bytes)


def atomic_append_jsonl(path: str | Path, obj: Any, *, keep_lines: int | None = None) -> None:
    """Append one JSONL row. Not fully atomic across readers, but never truncates existing.

    Optional keep_lines trims from the head after append (best-effort).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    if keep_lines is not None and keep_lines > 0:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > keep_lines:
                atomic_write_text(path, "\n".join(lines[-keep_lines:]) + "\n", min_bytes=1)
        except OSError:
            pass
