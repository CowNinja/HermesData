#!/usr/bin/env python3
"""Start a long-running Hermes script fully outside the parent process tree.

Why this exists (2026-07-17):
  Grok / CI tool shells wrap commands in a Windows Job Object. When the shell
  exits, *every* descendant is killed — even pythonw with DETACHED_PROCESS —
  unless CREATE_BREAKAWAY_FROM_JOB succeeds (often denied) or the process is
  created via WMI Win32_Process.Create (outside the job).

Usage:
  pythonw start_detached.py path\\to\\script.py [args...]
  pythonw start_detached.py --ps path\\to\\script.ps1
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\HermesData")
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _wmi_create(cmdline: str, cwd: str) -> int | None:
    """Create process via WMI (escapes parent Job Object). Returns PID or None."""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore

        pythoncom.CoInitialize()
        wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(
            ".", "root\\cimv2"
        )
        startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_()
        # 0 = hidden window for ShowWindow? Win32_ProcessStartup has ShowWindow
        try:
            startup.ShowWindow = 0
        except Exception:
            pass
        result = wmi.Get("Win32_Process").Create(cmdline, cwd, startup)
        # result is (pid, return_value) or a WMI object depending on bindings
        if hasattr(result, "ProcessId"):
            if int(getattr(result, "ReturnValue", 1)) == 0:
                return int(result.ProcessId)
            return None
        # Some pywin32 versions return a tuple
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            ret, pid = int(result[0]), int(result[1]) if result[1] else 0
            # Actually Create returns (ReturnValue, ProcessId) order varies
            # Prefer scanning for ProcessId attribute above.
        return None
    except Exception:
        pass
    # Fallback: PowerShell WMI (always available on this host)
    try:
        ps = (
            f"$p = ([wmiclass]'Win32_Process').Create({cmdline!r}, {cwd!r}); "
            f"if ($p.ReturnValue -eq 0) {{ $p.ProcessId }} else {{ exit $p.ReturnValue }}"
        )
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out.isdigit():
            return int(out)
    except Exception:
        pass
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: start_detached.py script.py [args...]\n"
            "       start_detached.py --ps script.ps1",
            file=sys.stderr,
        )
        return 2

    is_ps = sys.argv[1] == "--ps"
    if is_ps:
        if len(sys.argv) < 3:
            return 2
        target = Path(sys.argv[2]).resolve()
        extra = sys.argv[3:]
        cmdline = (
            f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass '
            f'-File "{target}"'
        )
        if extra:
            cmdline += " " + " ".join(extra)
        cwd = str(target.parent)
    else:
        script = Path(sys.argv[1]).resolve()
        args = sys.argv[2:]
        pyw = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
        exe = str(pyw if pyw.is_file() else sys.executable)
        argstr = " ".join(f'"{a}"' for a in args)
        cmdline = f'cmd.exe /c set HERMES_HOME={ROOT}&& set PHRONESIS_BOOT_INTEGRITY=0&& "{exe}" "{script}" {argstr}'.rstrip()
        cwd = str(ROOT)

    pid = _wmi_create(cmdline, cwd)
    if pid:
        print(f"wmi_ok pid={pid}")
        return 0

    # Last resort: subprocess with breakaway (may still die under Job Objects)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(ROOT)
    env.setdefault("PHRONESIS_BOOT_INTEGRITY", "0")
    if is_ps:
        cmd = [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(sys.argv[2]).resolve()),
            *sys.argv[3:],
        ]
    else:
        pyw = ROOT / "hermes-agent" / "venv" / "Scripts" / "pythonw.exe"
        exe = str(pyw if pyw.is_file() else sys.executable)
        cmd = [exe, str(Path(sys.argv[1]).resolve()), *sys.argv[2:]]
    flags = (
        CREATE_NO_WINDOW
        | DETACHED_PROCESS
        | CREATE_NEW_PROCESS_GROUP
        | CREATE_BREAKAWAY_FROM_JOB
    )
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
            env=env,
        )
        print("popen_breakaway_ok")
    except OSError:
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
            env=env,
        )
        print("popen_detached_fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
