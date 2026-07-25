#!/usr/bin/env python3
"""Popup storm suppressor (user-level, pythonw-safe, travel mode).

Cannot Disable Admin Highest tasks (Access denied). Instead:
  - END known flashy schtasks every run (stops mid-flight popups)
  - kill flashy console processes by cmdline (no powershell spawn)
  - hide visible console windows via ShowWindow(SW_HIDE)
  - stop Cua driver if running (AgentCursorOverlay)
  - ensure focus STOP files present
  - dedup dual dashboard if both present (never kill sovereign proxy)

Register:
  pythonw popup_storm_suppress.py --register
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(r"D:\HermesData\scripts")
STATE = Path(r"D:\HermesData\state")
RECEIPT = Path(r"D:\PhronesisVault\Operations\logs\popup-storm-suppress-latest.json")
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
TASK = "Hermes_Popup_Storm_Suppress"
FLASY = [
    "cua-driver-serve",
    "Phronesis-Guardian",
    "Phronesis-Grok-Direct-Bridge",
    "Phronesis-Grok-Hermes-Loop",
    "Phronesis-Image-Rider",
    "Phronesis-Start-At-Logon",
]
# Cmdline substrings that steal focus when launched as bare python/powershell.
FLASHY_CMD_RE = re.compile(
    r"(Phronesis-Guardian|Ensure-Grok-Direct-Bridge|grok_hermes_loop|"
    r"Phronesis-Image-Rider|AgentCursorOverlay|cua-driver\.exe.*serve|"
    r"Start-At-Logon|popup_storm_suppress\.ps1)",
    re.I,
)
# Never kill these even if pattern matches.
SAFE_CMD_RE = re.compile(
    r"(sovereign_openai_proxy|hermes_cli\.main|popup_storm_daemon|"
    r"popup_storm_suppress|popup_focus_enforce|ensure_qwythos|"
    r"ComfyUI\\\\main\.py|llama-server)",
    re.I,
)
CUA_CANDIDATES = [
    Path(r"C:\Users\CowNi\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe"),
    Path(r"C:\Users\CowNi\.cua-driver\packages\releases\0.7.0-x86_64-pc-windows-msvc\cua-driver.exe"),
]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        encoding="utf-8",
        errors="replace",
    )


def end_tasks() -> list[str]:
    ended = []
    for n in FLASY:
        try:
            r = run(["schtasks", "/End", "/TN", n], timeout=10)
            blob = (r.stdout or "") + (r.stderr or "")
            if r.returncode == 0 or "SUCCESS" in blob:
                ended.append(n)
        except Exception:
            pass
    return ended


def stop_cua() -> dict:
    out: dict = {"stopped": False}
    exe = next((p for p in CUA_CANDIDATES if p.is_file()), None)
    if not exe:
        try:
            pkg = Path(r"C:\Users\CowNi\.cua-driver\packages\releases")
            if pkg.is_dir():
                found = sorted(pkg.glob("*/cua-driver.exe"), reverse=True)
                exe = found[0] if found else None
        except Exception:
            exe = None
    if not exe:
        out["error"] = "no_exe"
        return out
    try:
        r = run([str(exe), "stop"], timeout=15)
        out["rc"] = r.returncode
        out["msg"] = ((r.stdout or "") + (r.stderr or ""))[-200:]
        out["stopped"] = True
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def ensure_focus_stops() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    body = f"popup_storm_suppress {utc()}\n"
    for name in (
        "silo_continuous.STOP",
        "silo_autonomous.STOP",
        "focus_mode.STOP",
        "popup_emergency.STOP",
    ):
        try:
            (STATE / name).write_text(body, encoding="utf-8")
        except Exception:
            pass


def _list_processes() -> list[tuple[int, str, str]]:
    """Return (pid, name, cmdline) via WMIC (CREATE_NO_WINDOW — no flash)."""
    rows: list[tuple[int, str, str]] = []
    try:
        r = run(
            [
                "wmic",
                "process",
                "get",
                "ProcessId,Name,CommandLine",
                "/FORMAT:CSV",
            ],
            timeout=25,
        )
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        if len(lines) < 2:
            return rows
        # CSV header: Node,CommandLine,Name,ProcessId
        for ln in lines[1:]:
            parts = ln.split(",")
            if len(parts) < 4:
                continue
            try:
                pid = int(parts[-1].strip())
            except ValueError:
                continue
            name = parts[-2].strip()
            cmd = ",".join(parts[1:-2]).strip().strip('"')
            rows.append((pid, name, cmd))
    except Exception:
        pass
    return rows


def kill_flashy_console_procs() -> list[int]:
    """Kill bare powershell/python processes that match flashy trampolines."""
    killed: list[int] = []
    me = os.getpid()
    for pid, name, cmd in _list_processes():
        if pid == me or pid <= 4:
            continue
        nlow = (name or "").lower()
        if nlow not in (
            "powershell.exe",
            "pwsh.exe",
            "python.exe",
            "cmd.exe",
            "conhost.exe",
        ):
            # Also stop cua-driver serve if present
            if nlow == "cua-driver.exe" and "serve" in (cmd or "").lower():
                pass
            else:
                continue
        if SAFE_CMD_RE.search(cmd or ""):
            continue
        if not FLASHY_CMD_RE.search(cmd or "") and nlow != "cua-driver.exe":
            continue
        try:
            run(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=8)
            killed.append(pid)
        except Exception:
            pass
    return killed


def hide_visible_flash_windows() -> int:
    """SW_HIDE any top-level window owned by flashy console PIDs."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        SW_HIDE = 0
        flash_pids = set()
        for pid, name, cmd in _list_processes():
            nlow = (name or "").lower()
            if nlow not in ("powershell.exe", "pwsh.exe", "python.exe", "cmd.exe"):
                continue
            if SAFE_CMD_RE.search(cmd or ""):
                continue
            if FLASHY_CMD_RE.search(cmd or ""):
                flash_pids.add(pid)
        if not flash_pids:
            return 0

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        hidden = [0]

        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in flash_pids:
                user32.ShowWindow(hwnd, SW_HIDE)
                hidden[0] += 1
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)
        # FreeConsole on self is no-op when pythonw; keep kernel32 ref
        _ = kernel32
        return hidden[0]
    except Exception:
        return 0


def dedup_pythonw(match: str) -> list[int]:
    """Kill older pythonw processes matching cmdline; keep lowest PID. No PowerShell."""
    killed: list[int] = []
    matches: list[int] = []
    pat = re.compile(match, re.I)
    for pid, name, cmd in _list_processes():
        if (name or "").lower() != "pythonw.exe":
            continue
        if pat.search(cmd or ""):
            matches.append(pid)
    if len(matches) <= 1:
        return killed
    matches.sort()
    keep = matches[0]
    for pid in matches[1:]:
        if pid == keep:
            continue
        try:
            run(["taskkill", "/PID", str(pid), "/F"], timeout=8)
            killed.append(pid)
        except Exception:
            pass
    return killed


def kill_orphan_comfy_dup() -> list[int]:
    """If two ComfyUI main.py, kill non-listeners (frees RAM/VRAM thrash)."""
    killed: list[int] = []
    comfy: list[tuple[int, str]] = []
    for pid, name, cmd in _list_processes():
        if "ComfyUI" in (cmd or "") and "main.py" in (cmd or ""):
            comfy.append((pid, cmd))
    if len(comfy) <= 1:
        return killed
    # Prefer process that owns 8188; kill others
    owner = None
    try:
        r = run(
            ["netstat", "-ano"],
            timeout=10,
        )
        for ln in (r.stdout or "").splitlines():
            if ":8188" in ln and "LISTENING" in ln.upper():
                parts = ln.split()
                if parts:
                    try:
                        owner = int(parts[-1])
                    except ValueError:
                        pass
    except Exception:
        owner = None
    for pid, _cmd in comfy:
        if owner is not None and pid == owner:
            continue
        if owner is None and pid == min(p for p, _ in comfy):
            continue  # keep oldest if unknown
        try:
            run(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=10)
            killed.append(pid)
        except Exception:
            pass
    return killed


def suppress() -> dict[str, Any]:
    ensure_focus_stops()
    rep: dict[str, Any] = {
        "ts": utc(),
        "ended": end_tasks(),
        "cua": stop_cua(),
        "killed_flashy": kill_flashy_console_procs(),
        "hidden_windows": hide_visible_flash_windows(),
        # Do NOT kill sovereign_openai_proxy — dual-proxy thrash left :8091 dead.
        "killed_dup_dash": dedup_pythonw(r"dashboard --port 9119"),
        "killed_orphan_comfy": kill_orphan_comfy_dup(),
    }
    try:
        sys.path.insert(0, str(SCRIPTS))
        from no_popup_law import quiet_user_ticks

        rep["quiet"] = quiet_user_ticks()
    except Exception as e:
        rep["quiet_err"] = str(e)[:120]
    try:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    except Exception:
        pass
    return rep


def register() -> dict:
    pyw = Path(r"D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe")
    if not pyw.is_file():
        pyw = Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe")
    script = str(SCRIPTS / "popup_storm_suppress.py")
    run(["schtasks", "/Delete", "/TN", TASK, "/F"])
    # Every 1 minute (daemon covers 5s; this is backup)
    tr = f'"{pyw}" "{script}"'
    r = run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK,
            "/TR",
            tr,
            "/SC",
            "MINUTE",
            "/MO",
            "1",
            "/F",
            "/RL",
            "LIMITED",
        ],
        timeout=30,
    )
    return {
        "ok": r.returncode == 0,
        "out": ((r.stdout or "") + (r.stderr or ""))[-400:],
        "task": TASK,
        "tr": tr,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.register:
        reg = register()
        print(json.dumps(reg, indent=2))
        rep = suppress()
        if args.json:
            print(json.dumps(rep, indent=2)[:2000])
        return 0 if reg.get("ok") else 1
    rep = suppress()
    print(
        json.dumps(
            rep
            if args.json
            else {
                "ts": rep["ts"],
                "ended_n": len(rep.get("ended") or []),
                "ended": rep.get("ended"),
                "killed_flashy": rep.get("killed_flashy"),
                "hidden_windows": rep.get("hidden_windows"),
                "killed_orphan_comfy": rep.get("killed_orphan_comfy"),
                "cua": (rep.get("cua") or {}).get("stopped"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
