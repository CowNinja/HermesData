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
    if not Path(exe).is_file():
        # still try PATH resolution via CreateProcess
        pass
    flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        flags |= CREATE_BREAKAWAY_FROM_JOB
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except OSError:
        # Job may forbid breakaway
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
