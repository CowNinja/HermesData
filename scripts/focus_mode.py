#!/usr/bin/env python3
"""Typing / remote-desktop focus mode ? stop silo relaunch storms that steal focus.

Research basis (see Operations/Focus-Steal-Prevention-CANONICAL-2026-07-17.md):
  - Task Scheduler + python.exe/powershell.exe attaches conhost and steals keyboard focus
  - STOP files are the established emergency brake (popup-emergency-2026-07-17)

Usage:
  pythonw focus_mode.py on     # create STOP files (safe while Jeff types / RDP)
  pythonw focus_mode.py off    # remove STOP files
  pythonw focus_mode.py status
  pythonw focus_mode.py off --resume-hidden   # also start daemons via hidden VBS
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(r"D:/HermesData/state")
# Popup/typing focus only. Silo STOP files are operator-owned via silo_ctl
# (Jeff clear/start). Writing silo_continuous/autonomous.STOP from focus_mode
# froze land/depth after intentional unfreeze (2026-07-26 cook).
STOPS = [
    STATE / "focus_mode.STOP",
]
VBS = Path(r"D:/HermesData/scripts/start_silo_daemons_hidden.vbs")
CREATE_NO_WINDOW = 0x08000000
# Shared law (USER_TICKS_QUIET + helpers)
if str(Path(r"D:/HermesData/scripts")) not in sys.path:
    sys.path.insert(0, str(Path(r"D:/HermesData/scripts")))
try:
    from no_popup_law import quiet_user_ticks, resume_user_ticks, write_law_state  # noqa: E402
except Exception:  # pragma: no cover
    quiet_user_ticks = None  # type: ignore
    resume_user_ticks = None  # type: ignore
    write_law_state = None  # type: ignore


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status() -> dict:
    focus = (STATE / "focus_mode.STOP").is_file()
    # Report silo STOP presence for observability without owning them.
    silo_stops = {
        "silo_continuous.STOP": (STATE / "silo_continuous.STOP").is_file(),
        "silo_autonomous.STOP": (STATE / "silo_autonomous.STOP").is_file(),
    }
    return {
        "at": utc(),
        "stops": {p.name: p.is_file() for p in STOPS},
        "silo_stops_readonly": silo_stops,
        "focus_mode": focus,
        "silo_stop_owner": "silo_ctl",
    }


def _stop_cua_driver() -> dict:
    """Stop Cua computer-use daemon (AgentCursorOverlay steals RDP focus).

    On-demand only during human typing: never leave serve OR mcp running under focus_mode.
    """
    out: dict = {"attempted": True, "stopped": False}
    candidates = [
        Path(r"C:\Users\CowNi\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe"),
        Path(r"C:\Users\CowNi\.cua-driver\packages\releases\0.7.0-x86_64-pc-windows-msvc\cua-driver.exe"),
    ]
    # Prefer newest package under .cua-driver if present
    try:
        pkg = Path(r"C:\Users\CowNi\.cua-driver\packages\releases")
        if pkg.is_dir():
            for p in sorted(pkg.glob("*/cua-driver.exe"), reverse=True):
                candidates.insert(0, p)
    except Exception:
        pass
    exe = next((c for c in candidates if c.is_file()), None)
    if not exe:
        out["error"] = "cua-driver.exe not found"
        return out
    try:
        r = subprocess.run(
            [str(exe), "stop"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out["rc"] = r.returncode
        out["stdout"] = ((r.stdout or "") + (r.stderr or ""))[-300:]
        out["stopped"] = r.returncode == 0 or "not running" in (out["stdout"] or "").lower()
    except Exception as exc:
        out["error"] = str(exc)[:200]
    # Also END the logon serve task if it is mid-run (user may END without Disable)
    try:
        subprocess.run(
            ["schtasks", "/End", "/TN", "cua-driver-serve"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out["schtask_end"] = "cua-driver-serve"
    except Exception:
        pass
    # Hermes computer_use spawns cua-driver.exe mcp (not serve) — taskkill all
    try:
        r2 = subprocess.run(
            ["taskkill", "/IM", "cua-driver.exe", "/F", "/T"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        blob = ((r2.stdout or "") + (r2.stderr or ""))
        out["taskkill_im_rc"] = r2.returncode
        out["taskkill_im_msg"] = blob[-200:]
        if r2.returncode == 0 or "SUCCESS" in blob.upper() or "not found" in blob.lower():
            out["stopped"] = True
    except Exception as exc:
        out["taskkill_im_error"] = str(exc)[:160]
    return out


def _end_admin_flashy_tasks() -> list[str]:
    """Best-effort END (not Disable) of known Admin residual flashy tasks."""
    names = [
        "Phronesis-Guardian",
        "Phronesis-Grok-Direct-Bridge",
        "Phronesis-Grok-Hermes-Loop",
        "Phronesis-Image-Rider",
        "Phronesis-Start-At-Logon",
        "cua-driver-serve",
    ]
    ended: list[str] = []
    for n in names:
        try:
            r = subprocess.run(
                ["schtasks", "/End", "/TN", n],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if r.returncode == 0 or "SUCCESS" in ((r.stdout or "") + (r.stderr or "")):
                ended.append(n)
        except Exception:
            pass
    return ended


def on(reason: str = "focus_mode") -> dict:
    STATE.mkdir(parents=True, exist_ok=True)
    body = f"{reason} {utc()}\n"
    for p in STOPS:
        p.write_text(body, encoding="utf-8")
    # popup_emergency.STOP — extra brake for trampolines that check it
    try:
        (STATE / "popup_emergency.STOP").write_text(body, encoding="utf-8")
    except Exception:
        pass
    tick = quiet_user_ticks() if quiet_user_ticks else {}
    cua = _stop_cua_driver()
    ended = _end_admin_flashy_tasks()
    rep = status()
    rep["action"] = "on"
    rep["user_ticks_disabled"] = tick
    rep["cua"] = cua
    rep["ended_flashy_tasks"] = ended
    if write_law_state:
        try:
            write_law_state({"focus_action": "on", "ticks": tick, "cua": cua, "ended": ended})
        except Exception:
            pass
    return rep


def off(*, resume_hidden: bool = False) -> dict:
    for p in STOPS:
        try:
            p.unlink(missing_ok=True)
        except OSError as exc:
            print(f"warn unlink {p}: {exc}", file=sys.stderr)
    tick = resume_user_ticks() if resume_user_ticks else {}
    rep = status()
    rep["action"] = "off"
    rep["user_ticks_enabled"] = tick
    if write_law_state:
        try:
            write_law_state({"focus_action": "off", "ticks": tick})
        except Exception:
            pass
    if resume_hidden and VBS.is_file():
        try:
            subprocess.run(
                ["wscript.exe", "//B", str(VBS)],
                check=False,
                timeout=30,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            rep["resume"] = "wscript_hidden_vbs"
        except Exception as exc:
            rep["resume_err"] = str(exc)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["on", "off", "status"])
    ap.add_argument("--reason", default="focus_mode typing/remote")
    ap.add_argument(
        "--resume-hidden",
        action="store_true",
        help="with off: start silo daemons via start_silo_daemons_hidden.vbs",
    )
    args = ap.parse_args()
    if args.cmd == "on":
        rep = on(args.reason)
    elif args.cmd == "off":
        rep = off(resume_hidden=args.resume_hidden)
    else:
        rep = status()
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
