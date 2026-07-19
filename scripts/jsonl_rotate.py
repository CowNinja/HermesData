#!/usr/bin/env python3
"""Compatibility shim → jsonl_log_rotator (SSOT).

Do not duplicate rotation logic here. Callers may `import jsonl_rotate`.
Research 2026-07-19: existing jsonl_log_rotator.py already covers rename +
copytruncate + KNOWN_FAT_LOGS + cron entry JSONL-Log-Rotator-6h.
"""
from __future__ import annotations

from jsonl_log_rotator import (  # noqa: F401
    DEFAULT_BACKUPS,
    DEFAULT_MAX_BYTES,
    KNOWN_FAT_LOGS,
    append_jsonl,
    rotate_if_needed,
    rotate_many,
)

__all__ = [
    "DEFAULT_BACKUPS",
    "DEFAULT_MAX_BYTES",
    "KNOWN_FAT_LOGS",
    "append_jsonl",
    "rotate_if_needed",
    "rotate_many",
    "maybe_rotate_many",
    "rotate_known_logs",
]


def rotate_known_logs(*, max_bytes=DEFAULT_MAX_BYTES, backups=DEFAULT_BACKUPS, mode="copytruncate"):
    """Rotate KNOWN_FAT_LOGS (copytruncate default for multi-writer)."""
    return rotate_many(KNOWN_FAT_LOGS, max_bytes=max_bytes, backups=backups, mode=mode)


def maybe_rotate_many(paths, *, max_bytes=DEFAULT_MAX_BYTES, backups=DEFAULT_BACKUPS, mode="rename"):
    """Thin multi-path helper used by ops receipts."""
    out = {}
    for path in paths:
        r = rotate_if_needed(path, max_bytes=max_bytes, backups=backups, mode=mode)
        out[str(path)] = bool(r.get("rotated")) if isinstance(r, dict) else bool(r)
    return out


if __name__ == "__main__":
    import sys
    from jsonl_log_rotator import main

    raise SystemExit(main(sys.argv[1:]))
