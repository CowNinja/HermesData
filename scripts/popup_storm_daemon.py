#!/usr/bin/env python3
"""Long-running popup storm daemon (travel mode, no Admin).

Lightweight loop — DO NOT call full suppress()/WMIC every tick (that freezes RDP).

Cadence (2026-07-26 RDP-calm retune; was 1s/2s/5s/10s/60s):
  - every ~5s: hide flashy windows + UAC consent kill + restore protected
  - every ~30s: END flashy schtasks
  - every ~60s: kill elevation spawners
  - every ~120s: ensure focus STOPs + stop CUA
  - every ~10m: one full suppress() (process kill pass)

Single-instance (2026-07-25 harden):
  1. If launched via venv Scripts\\pythonw.exe, os.execv into home pythonw
     (uv/venv trampoline otherwise leaves parent+child both running this file).
  2. Win32 named mutex Local\\HermesPopupStormDaemon — second start exits 0.
  3. msvcrt lock on popup_storm_daemon.lock as secondary signal.
  No PowerShell process scans on the start path (those hung dual-start races).

Start: pythonw popup_storm_daemon.py
       preferred: home pythonw (C:\\Users\\...\\Python311\\pythonw.exe)
Stop:  write D:\\HermesData\\state\\popup_storm_daemon.STOP

Never hides Windows Terminal / Cascadia / grok titles — see popup_storm_suppress.PROTECT_*.
"""
from __future__ import annotations

import atexit
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state")
sys.path.insert(0, str(SCRIPTS))

from popup_storm_suppress import (  # noqa: E402
    end_tasks,
    ensure_focus_stops,
    hide_visible_flash_windows,
    kill_elevation_spawners,
    kill_uac_consent,
    restore_protected_work_windows,
    stop_cua,
    suppress,
)

PID_FILE = STATE / "popup_storm_daemon.pid"
STOP_FILE = STATE / "popup_storm_daemon.STOP"
LOCK_FILE = STATE / "popup_storm_daemon.lock"
MUTEX_NAME = "Local\\HermesPopupStormDaemon"

_lock_fh = None
_mutex_handle = None


def _reexec_if_venv_pythonw() -> None:
    """Replace venv Scripts\\pythonw with home pythonw so only one process runs.

    Measured 2026-07-25: venv pythonw leaves a parent+child both executing this
    script (parent=venv path, child=home path). Mutex alone races; execv fixes it.
    """
    if sys.platform != "win32":
        return
    try:
        exe = Path(sys.executable).resolve()
    except Exception:
        return
    name = exe.name.lower()
    if name not in ("pythonw.exe", "python.exe"):
        return
    low = str(exe).lower().replace("/", "\\")
    # venv layout: ...\\venv\\Scripts\\pythonw.exe
    if "\\scripts\\" not in low:
        return
    if "venv" not in low and ".venv" not in low:
        return
    # Prefer same basename (pythonw stays windowless)
    home_dir = Path(getattr(sys, "base_prefix", sys.prefix) or sys.prefix)
    target = home_dir / name
    if not target.is_file():
        target = home_dir / "pythonw.exe"
    if not target.is_file():
        return
    try:
        if target.resolve() == exe:
            return
    except Exception:
        if str(target).lower() == str(exe).lower():
            return
    script = str(Path(__file__).resolve())
    args = [str(target), script, *sys.argv[1:]]
    try:
        os.execv(str(target), args)
    except OSError:
        return


def _release_lock() -> None:
    global _lock_fh, _mutex_handle
    fh = _lock_fh
    _lock_fh = None
    if fh is not None:
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            fh.close()
        except Exception:
            pass
    mh = _mutex_handle
    _mutex_handle = None
    if mh and sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.ReleaseMutex(mh)
            ctypes.windll.kernel32.CloseHandle(mh)
        except Exception:
            pass
    try:
        if PID_FILE.is_file():
            cur = PID_FILE.read_text(encoding="utf-8", errors="replace").strip()
            if cur.split()[0] == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _try_mutex() -> bool | None:
    """Win32 named mutex. True=owned, False=peer holds, None=unavailable."""
    global _mutex_handle
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD
        ERROR_ALREADY_EXISTS = 183
        # bInitialOwner=False then Wait — clearer ownership semantics
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return None
        WAIT_OBJECT_0 = 0
        WAIT_TIMEOUT = 0x00000102
        # Non-blocking acquire
        wr = kernel32.WaitForSingleObject(handle, 0)
        if wr == WAIT_OBJECT_0:
            _mutex_handle = handle
            return True
        # Someone else owns it (or abandoned we didn't get — treat as peer)
        kernel32.CloseHandle(handle)
        if wr == WAIT_TIMEOUT:
            return False
        # WAIT_ABANDONED_0 (0x80) counts as ownership — recreate properly
        if wr == 0x00000080:
            handle2 = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            if handle2 and kernel32.WaitForSingleObject(handle2, 0) == WAIT_OBJECT_0:
                _mutex_handle = handle2
                return True
            if handle2:
                kernel32.CloseHandle(handle2)
        return False
    except Exception:
        return None


def _try_msvcrt_lock() -> bool:
    global _lock_fh
    try:
        fh = open(LOCK_FILE, "a+b")
    except OSError:
        return False
    try:
        fh.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return False
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n{time.time():.3f}\n".encode("ascii", "replace"))
        fh.flush()
    except Exception:
        pass
    _lock_fh = fh
    return True


def _acquire_single_instance() -> bool:
    STATE.mkdir(parents=True, exist_ok=True)
    owned = _try_mutex()
    if owned is False:
        return False
    if owned is True:
        _try_msvcrt_lock()  # best-effort secondary
    else:
        if not _try_msvcrt_lock():
            return False
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    atexit.register(_release_lock)
    return True


def main() -> int:
    # Collapse venv trampoline → single home pythonw process first.
    _reexec_if_venv_pythonw()

    STATE.mkdir(parents=True, exist_ok=True)
    if STOP_FILE.is_file():
        try:
            STOP_FILE.unlink()
        except Exception:
            pass

    if not _acquire_single_instance():
        return 0  # quiet no-op

    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

    tick = 0
    # Base tick ~5s (was ~1s). RDP-calm 2026-07-26.
    TICK_SLICES = 20  # 20 * 0.25s = 5s
    ensure_focus_stops()
    while True:
        if STOP_FILE.is_file():
            break
        # Every tick (~5s): UAC consent is the worst RDP blocker — kill first.
        try:
            kill_uac_consent()
        except Exception:
            pass
        try:
            hide_visible_flash_windows()
        except Exception:
            pass
        try:
            # Un-minimize Grok/Cascadia if something iconic'd it (CUA/RDP/flash).
            restore_protected_work_windows()
        except Exception:
            pass
        # END flashy schtasks every tick (~5s). HighestAvailable (cua/GPU)
        # re-fires UAC if left Running; END is the only Medium-IL brake.
        if tick % 1 == 0:
            try:
                end_tasks()
            except Exception:
                pass
        # elevation spawners every tick (~5s) — catch cua Start-Process early
        if tick % 1 == 0:
            try:
                kill_elevation_spawners()
            except Exception:
                pass
        # focus stops + CUA ~every 120s (was ~10s)
        if tick % 24 == 0:
            try:
                ensure_focus_stops()
                stop_cua()
            except Exception:
                pass
        # full suppress ~every 10m (was ~60s)
        if tick % 120 == 0 and tick > 0:
            try:
                suppress()
            except Exception:
                pass
        tick += 1
        for _ in range(TICK_SLICES):
            if STOP_FILE.is_file():
                break
            time.sleep(0.25)

    _release_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
