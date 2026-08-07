#!/usr/bin/env python3
"""Silent focus-guard daemon (2026-08-05 hard rewrite).

WHY REWRITE:
  Old loop every ~5s spawned tasklist/wmic/schtasks/cmd → conhost flash
  every 5–10s that killed STT/typing for months. Measured: with this daemon
  dead, 15s watch showed ZERO tasklist/cmd spawns.

LAW:
  - Hot path: PURE ctypes only (EnumWindows SW_HIDE bare consoles).
  - NO subprocess on the hot path. Ever.
  - Heavy passes (schtasks End, rare WMI bare-PS kill) at most every 10 minutes.
  - Never SW_RESTORE work windows every tick (that steals focus too).
  - Single instance mutex. pythonw + FreeConsole.

Start:  pythonw popup_storm_daemon.py
        or: pythonw start_detached.py popup_storm_daemon.py
Stop:   write D:\\HermesData\\state\\popup_storm_daemon.STOP
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

PID_FILE = STATE / "popup_storm_daemon.pid"
STOP_FILE = STATE / "popup_storm_daemon.STOP"
LOCK_FILE = STATE / "popup_storm_daemon.lock"
HB_FILE = STATE / "popup_storm_daemon_heartbeat.json"
MUTEX_NAME = "Local\\HermesPopupStormDaemonSilent"
LOG = Path(r"D:\HermesData\logs\popup-storm-daemon.log")

# Hot path: hide only, ~3s. Heavy path: rare.
HOT_SLEEP_SEC = 3.0
HEAVY_EVERY_TICKS = 200  # ~10 min at 3s

_lock_fh = None
_mutex_handle = None


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _reexec_if_venv_pythonw() -> None:
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
    if "\\scripts\\" not in low or ("venv" not in low and ".venv" not in low):
        return
    home_dir = Path(getattr(sys, "base_prefix", sys.prefix) or sys.prefix)
    target = home_dir / "pythonw.exe"
    if not target.is_file() or target.resolve() == exe:
        return
    try:
        os.execv(str(target), [str(target), str(Path(__file__).resolve()), *sys.argv[1:]])
    except OSError:
        return


def _release_lock() -> None:
    global _lock_fh, _mutex_handle
    if _lock_fh is not None:
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    _lock_fh.seek(0)
                    msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            _lock_fh.close()
        except Exception:
            pass
        _lock_fh = None
    if _mutex_handle and sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None
    try:
        if PID_FILE.is_file() and PID_FILE.read_text(encoding="utf-8").strip().startswith(
            str(os.getpid())
        ):
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _acquire_single_instance() -> bool:
    global _mutex_handle, _lock_fh
    STATE.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            k = ctypes.windll.kernel32
            k.CreateMutexW.restype = wintypes.HANDLE
            h = k.CreateMutexW(None, False, MUTEX_NAME)
            if h and k.WaitForSingleObject(h, 0) == 0:
                _mutex_handle = h
            else:
                if h:
                    k.CloseHandle(h)
                return False
        except Exception:
            pass
    try:
        fh = open(LOCK_FILE, "a+b")
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        _lock_fh = fh
    except OSError:
        return False
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    atexit.register(_release_lock)
    return True


def _hot_tick() -> int:
    """Pure ctypes: hide flashy tool/error consoles only. Returns hide count.

    2026-08-07: interactive 'Windows PowerShell' / 'Command Prompt' are spared.
    """
    from win_silent_proc import hide_window_titles

    return hide_window_titles(bare_console_only=True)


def _heavy_tick() -> dict:
    """Rare: end elevating schtasks + kill flashy elevators (CREATE_NO_WINDOW).

    Does NOT kill bare explorer PowerShell (user shells). ~every 10 minutes.
    """
    out: dict = {}
    try:
        from popup_storm_suppress import (
            end_tasks,
            kill_flashy_console_procs,
            stop_cua,
        )

        out["ended"] = end_tasks()
        out["killed"] = kill_flashy_console_procs()
        out["cua"] = stop_cua()
    except Exception as e:
        out["err"] = str(e)[:160]
    return out


def _hb(tick: int, hidden: int, heavy: dict | None = None) -> None:
    try:
        import json
        from datetime import datetime, timezone

        payload = {
            "pid": os.getpid(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "tick": tick,
            "last_hidden": hidden,
            "mode": "silent_ctypes_hotpath",
            "heavy": heavy,
        }
        HB_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    _reexec_if_venv_pythonw()
    STATE.mkdir(parents=True, exist_ok=True)

    # If STOP present at start: honor it and exit (do not auto-clear — Jeff gate).
    if STOP_FILE.is_file():
        _log("exit: STOP file present")
        return 0

    if not _acquire_single_instance():
        return 0

    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

    _log(f"silent daemon START pid={os.getpid()} hot={HOT_SLEEP_SEC}s heavy_every={HEAVY_EVERY_TICKS}")
    tick = 0
    while True:
        if STOP_FILE.is_file():
            _log("STOP file → exit")
            break
        hidden = 0
        try:
            hidden = _hot_tick()
        except Exception as e:
            _log(f"hot err: {e}")
        heavy = None
        if tick > 0 and tick % HEAVY_EVERY_TICKS == 0:
            try:
                heavy = _heavy_tick()
                _log(f"heavy {heavy}")
            except Exception as e:
                _log(f"heavy err: {e}")
        if tick % 20 == 0:
            _hb(tick, hidden, heavy)
        tick += 1
        # sleep in slices so STOP is responsive
        for _ in range(int(HOT_SLEEP_SEC * 4)):
            if STOP_FILE.is_file():
                break
            time.sleep(0.25)

    _release_lock()
    _log("exit clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
