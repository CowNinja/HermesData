"""Detach from any console so background workers never steal keyboard focus."""
from __future__ import annotations

import sys


def free_console() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # Detach from parent console (if any). No-op if none attached.
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


free_console()
