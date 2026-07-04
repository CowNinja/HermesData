"""Windows helpers to run child processes without flashing console windows."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)


def _apply_hidden_startup(kwargs: dict[str, Any]) -> None:
    if sys.platform != "win32":
        return
    flags = int(kwargs.get("creationflags") or 0)
    kwargs["creationflags"] = flags | CREATE_NO_WINDOW | DETACHED_PROCESS
    startupinfo = kwargs.get("startupinfo")
    if startupinfo is None:
        startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startupinfo


def prefer_pythonw(executable: str) -> str:
    """Use pythonw.exe on Windows to avoid console flashes for GUI-less scripts."""
    if sys.platform != "win32":
        return executable
    path = Path(executable)
    if path.name.lower() != "python.exe":
        return executable
    pythonw = path.with_name("pythonw.exe")
    return str(pythonw) if pythonw.is_file() else executable


def hidden_powershell_args(script: str, *extra: str) -> list[str]:
    """Build a PowerShell invocation that avoids visible windows on Windows."""
    args = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        script,
        *extra,
    ]
    return args


def hidden_powershell_command(cmd: str) -> list[str]:
    """Hidden PowerShell -Command invocation (for inline script blocks)."""
    return [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-Command",
        cmd,
    ]


def run_hidden(args: list[str] | tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    _apply_hidden_startup(kwargs)
    return subprocess.run(list(args), **kwargs)


def popen_hidden(args: list[str] | tuple[str, ...], **kwargs: Any) -> subprocess.Popen[Any]:
    _apply_hidden_startup(kwargs)
    return subprocess.Popen(list(args), **kwargs)