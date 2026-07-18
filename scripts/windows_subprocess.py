"""Windows helpers to run child processes without flashing console windows."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
# Escape parent Job Objects (Grok shell / schtasks / PowerShell jobs kill children on exit).
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _apply_hidden_startup(kwargs: dict[str, Any], *, detach: bool = False) -> None:
    """Hide console; optionally detach from parent job/console.

    NOTE: Do NOT combine detach=True with parent-owned file handles for stdout/stderr
    on long-lived daemons — when the parent exits those handles close and the child dies.
    Prefer CREATE_NO_WINDOW + DEVNULL (or let the child open its own logs).

    Daemons also need CREATE_BREAKAWAY_FROM_JOB so agent/CI Job Objects do not kill them
    when the launching shell command ends.
    """
    if sys.platform != "win32":
        return
    flags = int(kwargs.get("creationflags") or 0)
    flags |= CREATE_NO_WINDOW
    if detach:
        flags |= (
            DETACHED_PROCESS
            | CREATE_NEW_PROCESS_GROUP
            | CREATE_BREAKAWAY_FROM_JOB
        )
    kwargs["creationflags"] = flags
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
    """Synchronous hidden run (waits). Never detaches — parent owns the wait."""
    _apply_hidden_startup(kwargs, detach=False)
    return subprocess.run(list(args), **kwargs)


def popen_hidden(args: list[str] | tuple[str, ...], **kwargs: Any) -> subprocess.Popen[Any]:
    """Background-friendly Popen with no console window.

    Default: CREATE_NO_WINDOW only (safe with redirected stdio that outlives parent
    only if handles stay open; prefer DEVNULL + child-owned logs for daemons).
    Pass detach=True only when stdout/stderr are DEVNULL or child-owned.
    """
    detach = bool(kwargs.pop("detach", False))
    _apply_hidden_startup(kwargs, detach=detach)
    try:
        return subprocess.Popen(list(args), **kwargs)
    except OSError:
        # Job may forbid CREATE_BREAKAWAY_FROM_JOB — retry without it.
        if detach and (int(kwargs.get("creationflags") or 0) & CREATE_BREAKAWAY_FROM_JOB):
            flags = int(kwargs.get("creationflags") or 0) & ~CREATE_BREAKAWAY_FROM_JOB
            kwargs["creationflags"] = flags
            return subprocess.Popen(list(args), **kwargs)
        raise


def popen_daemon(args: list[str] | tuple[str, ...], **kwargs: Any) -> subprocess.Popen[Any]:
    """Long-lived background worker: no console, no inherited log handles.

    Forces stdout/stderr to DEVNULL unless caller already set them to DEVNULL.
    Child scripts must write their own log files.
    Prefers breakaway-from-job so agent shells / scheduled hosts don't kill us.
    """
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    kwargs.setdefault("stderr", subprocess.DEVNULL)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    kwargs["detach"] = True
    return popen_hidden(args, **kwargs)
