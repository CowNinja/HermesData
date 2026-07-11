#!/usr/bin/env python3
"""Check BW dedupe apply health; report if stuck or done; no secrets."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(r"D:\HermesData\state\secrets-work\bw-dedupe-apply-log.txt")
SUMMARY = Path(r"D:\HermesData\state\secrets-work\bw-dedupe-apply-summary.json")


def main() -> int:
    out = {"at": datetime.now(timezone.utc).isoformat()}
    if LOG.is_file():
        lines = LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        out["log_lines"] = len(lines)
        out["tail"] = lines[-8:]
        # parse last progress
        for line in reversed(lines):
            if "progress" in line and "/" in line:
                out["last_progress_line"] = line
                break
            if "mode_end=APPLY" in line or "mode_end" in line:
                out["mode_end"] = line
                break
    if SUMMARY.is_file():
        try:
            out["summary"] = json.loads(SUMMARY.read_text(encoding="utf-8"))
        except Exception:
            out["summary"] = None
    out["resume_hint"] = (
        "If stuck >20m with no new log lines, re-run: "
        'powershell -NoProfile -ExecutionPolicy Bypass -File '
        '"D:\\HermesData\\scripts\\bw_dedupe_apply.ps1" -Apply'
    )
    print(json.dumps(out, indent=2)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
