#!/usr/bin/env python3
"""Launch a console subsystem binary with CREATE_NO_WINDOW (no focus steal).

Use from Task Scheduler via pythonw.exe so the launcher itself has no console:

  pythonw.exe D:\\HermesData\\scripts\\launch_console_hidden.py -- \\
    D:\\path\\to\\llama-server.exe --host 127.0.0.1 --port 8090 ...

Everything after the first standalone `--` is the child command.
Without `--`, argv[1:] is the child command.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: launch_console_hidden.py [--] exe [args...]", file=sys.stderr)
        return 2
    if args[0] == "--":
        args = args[1:]
    if not args:
        return 2
    exe = args[0]
    exe_path = Path(exe)
    cwd = str(exe_path.parent) if exe_path.is_file() else None
    if not exe_path.is_file():
        # still try PATH resolution via CreateProcess
        pass
    # Optional boot log (env SILO_LLAMA_BOOT_LOG=1) for diagnose
    import os

    log_path = None
    if os.environ.get("SILO_LLAMA_BOOT_LOG") == "1":
        log_dir = Path(r"D:\HermesData\state\llama_boot")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "llama-server-boot.log"
    flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL
    err = out
    try:
        flags |= CREATE_BREAKAWAY_FROM_JOB
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=flags,
            close_fds=True,
            cwd=cwd,
        )
    except OSError:
        # Job may forbid breakaway
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=flags,
            close_fds=True,
            cwd=cwd,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
