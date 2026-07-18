#!/usr/bin/env python3
"""Cron entry: scan RP image pipeline bottlenecks and auto-fix."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNER = ROOT / "scripts" / "ops" / "rp_bottleneck_scanner.py"


def main() -> int:
    # Free any console attached to this cron tick (gateway may use python.exe briefly).
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    pipeline = ROOT / "scripts" / "ops" / "watch_comfy_pipeline.py"
    if pipeline.is_file():
        subprocess.run(
            [sys.executable, str(pipeline), "--once"],
            cwd=str(ROOT),
            timeout=30,
            check=False,
            creationflags=flags,
        )
    proc = subprocess.run(
        [sys.executable, str(SCANNER), "--fix"],
        cwd=str(ROOT),
        timeout=120,
        check=False,
        creationflags=flags,
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())