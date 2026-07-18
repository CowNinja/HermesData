#!/usr/bin/env python3
"""Shared size-based log/JSONL rotator for Phronesis ops logs.

Two modes:
  rename  — classic cascade path -> path.1 -> path.2 (safe when writer reopens each append)
  copytruncate — copy then truncate in place (safe when long-lived FD holds the path;
                 preferred for multi-process writers that never reopen)

Research (2026-07-18): Python RotatingFileHandler is single-process; multi-writer
stacks need copytruncate (logrotate pattern) or rotate-before-open on every write.

Usage:
  from jsonl_log_rotator import rotate_if_needed, append_jsonl
  rotate_if_needed(path, max_bytes=8<<20, backups=3, mode="copytruncate")
  append_jsonl(path, {"event": "tick"})  # rotates first

  CLI:
  python jsonl_log_rotator.py --once          # rotate known fat Phronesis logs
  python jsonl_log_rotator.py PATH [PATH...]  # rotate listed paths if over limit
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_MAX_BYTES = 4 * 1024 * 1024  # 4 MiB — ops JSONL grows fast; agent.log has its own 5MB hermes rot
DEFAULT_BACKUPS = 3

# Known fat ops logs (audit 2026-07-18). agent.log already has hermes rotation;
# include here for defensive one-shot if primary handler fails.
KNOWN_FAT_LOGS: List[Path] = [
    Path(r"D:\PhronesisVault\Operations\logs\operator-console.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\discord-proxy-ingest-trace.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\sovereign-memory.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\sovereign-stack-watchdog.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\model-management-agent.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\model-management-agent-reflection.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\model-rotation.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\sovereign-proxy.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\generation-provenance-trace.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\fleet-dispatch.jsonl"),
    Path(r"D:\PhronesisVault\Operations\logs\vram-pin-telemetry.jsonl"),
    Path(r"D:\HermesData\logs\agent.log"),
    Path(r"D:\HermesData\logs\errors.log"),
    Path(r"D:\HermesData\logs\gateway.log"),
    Path(r"D:\HermesData\logs\stack-healing-once.jsonl"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rotate_if_needed(
    path: Path | str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    mode: str = "rename",
) -> Dict[str, Any]:
    """Rotate path when size exceeds max_bytes.

    mode:
      rename       — path -> path.1 -> ... (writer must reopen path after)
      copytruncate — copy to path.1, truncate path to 0 (keeps inode/FD)

    Returns status dict (never raises).
    """
    p = Path(path)
    result: Dict[str, Any] = {
        "path": str(p),
        "rotated": False,
        "mode": mode,
        "reason": "ok",
    }
    try:
        if not p.exists():
            result["reason"] = "missing"
            return result
        size = p.stat().st_size
        result["size"] = size
        if size <= max_bytes:
            result["reason"] = "under_limit"
            return result
        if backups < 1:
            backups = 1
        mode_l = (mode or "rename").strip().lower()
        if mode_l not in ("rename", "copytruncate"):
            mode_l = "rename"
            result["mode"] = mode_l

        # Cascade backups: .(n) <- .(n-1) ... .2 <- .1
        for i in range(backups - 1, 0, -1):
            older = Path(f"{p}.{i + 1}")
            newer = Path(f"{p}.{i}")
            if older.exists():
                try:
                    older.unlink()
                except OSError:
                    pass
            if newer.exists():
                try:
                    newer.rename(older)
                except OSError:
                    # fallback copy+unlink
                    try:
                        shutil.copy2(newer, older)
                        newer.unlink()
                    except OSError:
                        pass

        first = Path(f"{p}.1")
        if mode_l == "copytruncate":
            if first.exists():
                try:
                    first.unlink()
                except OSError:
                    pass
            shutil.copy2(p, first)
            # Truncate in place (preserve path for open FDs)
            with open(p, "r+b") as fh:
                fh.truncate(0)
            result["rotated"] = True
            result["reason"] = "copytruncate"
            result["backup"] = str(first)
            return result

        # rename mode
        if first.exists():
            try:
                first.unlink()
            except OSError:
                pass
        try:
            p.rename(first)
        except OSError:
            # Windows: file locked — fall back to copytruncate
            shutil.copy2(p, first)
            with open(p, "r+b") as fh:
                fh.truncate(0)
            result["rotated"] = True
            result["reason"] = "rename_fallback_copytruncate"
            result["backup"] = str(first)
            return result
        result["rotated"] = True
        result["reason"] = "rename"
        result["backup"] = str(first)
        return result
    except Exception as exc:
        result["reason"] = f"error:{exc}"
        return result


def append_jsonl(
    path: Path | str,
    event: Dict[str, Any],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    mode: str = "rename",
    stamp: bool = True,
) -> None:
    """Rotate-if-needed then append one JSON line (UTF-8)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rotate_if_needed(p, max_bytes=max_bytes, backups=backups, mode=mode)
    row = dict(event)
    if stamp and "timestamp" not in row:
        row = {"timestamp": _utc_now(), **row}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def rotate_many(
    paths: Iterable[Path | str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    mode: str = "copytruncate",
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in paths:
        out.append(
            rotate_if_needed(path, max_bytes=max_bytes, backups=backups, mode=mode)
        )
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rotate fat Phronesis/Hermes logs")
    ap.add_argument(
        "paths",
        nargs="*",
        help="Paths to rotate (default: --once known set)",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="Rotate KNOWN_FAT_LOGS (copytruncate)",
    )
    ap.add_argument(
        "--max-mb",
        type=float,
        default=float(DEFAULT_MAX_BYTES) / (1024 * 1024),
        help=f"Max size in MiB before rotate (default {DEFAULT_MAX_BYTES // (1024 * 1024)})",
    )
    ap.add_argument("--backups", type=int, default=DEFAULT_BACKUPS)
    ap.add_argument(
        "--mode",
        choices=("rename", "copytruncate"),
        default="copytruncate",
        help="Default copytruncate for multi-process writers",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON results")
    ap.add_argument(
        "--silent-ok",
        action="store_true",
        help="No-agent cron mode: empty stdout when nothing rotated (exit 0); "
        "print only when rotated_count>0 or --json",
    )
    args = ap.parse_args(argv)

    max_bytes = int(args.max_mb * 1024 * 1024)
    if args.once or not args.paths:
        paths: List[Path | str] = list(KNOWN_FAT_LOGS)
    else:
        paths = list(args.paths)

    results = rotate_many(
        paths, max_bytes=max_bytes, backups=args.backups, mode=args.mode
    )
    rotated = [r for r in results if r.get("rotated")]
    if args.json:
        # JSON always emits (ops artifact); pair with deliver=local
        print(json.dumps({"rotated_count": len(rotated), "results": results}, indent=2))
    elif args.silent_ok and not rotated:
        # Healthy no-op for Hermes no_agent: empty stdout = silent delivery
        return 0
    else:
        for r in results:
            flag = "ROTATED" if r.get("rotated") else r.get("reason", "?")
            sz = r.get("size")
            sz_s = f"{sz}B" if isinstance(sz, int) else "-"
            print(f"{flag:28} {sz_s:>12}  {r.get('path')}")
        print(f"--- rotated {len(rotated)}/{len(results)} ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
