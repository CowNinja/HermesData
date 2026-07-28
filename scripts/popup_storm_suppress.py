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
    "GPU Tweak III",
]
# Cmdline substrings that steal focus when launched as bare python/powershell.
# 2026-07-26: do NOT match launch_hidden_ps / Guardian-Body ? those are the
# silent pythonw Hidden twin path. Only bare schtask parents + elevators.
FLASHY_CMD_RE = re.compile(
    r"(Phronesis-Guardian\.ps1|Ensure-Grok-Direct-Bridge\.ps1|grok_hermes_loop|"
    r"Start-Image-Rider|AgentCursorOverlay|cua-driver\.exe.*serve|"
    r"Start-At-Logon|popup_storm_suppress\.ps1|GPU\s*Tweak)",
    re.I,
)
# Window titles that flash/steal focus under RDP (hide, do not kill OS-critical).
# NOTE: Do NOT match bare "PowerShell" / "Windows PowerShell" ? Windows Terminal
# Grok Build tabs use those titles and were being SW_HIDE'd mid-typing (2026-07-25).
FLASHY_TITLE_RE = re.compile(
    r"(SOUI_DUMMY_WND|"
    r"GPU\s*Tweak|"
    r"Select\s+.*\.ps1|"
    r"Application Error|"
    r"tasklist\.exe|"
    r"pdftoppm\.exe|pdftotext\.exe|tesseract\.exe|"
    r"has stopped working|"
    r"Windows PowerShell has stopped|"
    r"\.NET Runtime|"
    r"Fatal error|"
    r"Python .* crashed)",
    re.I,
)
# Never hide these window classes (Jeff's typing surface under RDP).
PROTECT_CLASS_RE = re.compile(
    r"(CASCADIA_HOSTING_WINDOW_CLASS|Windows Terminal)",
    re.I,
)
# Never hide titles that look like the intentional Grok Build / work terminal.
PROTECT_TITLE_RE = re.compile(
    r"(\bgrok\b|Grok Build|Composer|Claude|Cursor|Phronesis|HermesData|"
    r"Windows Terminal)",
    re.I,
)
# Classic conhost-only titles (exact). Never match Windows Terminal tab titles.
BARE_CONSOLE_TITLE_RE = re.compile(
    r"^(Administrator:\s*)?(Windows PowerShell|Command Prompt)$"
    r"|^Select\s+.+\.ps1$",
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
    """END only tasks that can leave long-running focus stealers (CUA/GPU/logon).

    Do NOT End Guardian/Bridge/Loop/Image-Rider when lockdown is on ? those
    trampolines now exit 0 immediately. Force-End was producing Last Result
    267014 (TERMINATED), which Task Scheduler UI surfaces as an *error* popup.
    """
    lockdown = (STATE / "popup_lockdown.ON").is_file() or (
        STATE / "popup_emergency.STOP"
    ).is_file() or (STATE / "focus_mode.STOP").is_file()
    # Always end these ? they start real daemons/overlays
    always = ["cua-driver-serve", "GPU Tweak III", "Phronesis-Start-At-Logon"]
    # Only end flashy PS trampolines if NOT under lockdown (they self-exit 0)
    trampolines = [
        "Phronesis-Guardian",
        "Phronesis-Grok-Direct-Bridge",
        "Phronesis-Grok-Hermes-Loop",
        "Phronesis-Image-Rider",
    ]
    names = list(always)
    if not lockdown:
        names.extend(trampolines)
    # Under lockdown trampolines exit 0 themselves ? do not End them (avoids 267014 "error").
    ended = []
    for n in names:
        try:
            r = run(["schtasks", "/End", "/TN", n], timeout=10)
            blob = (r.stdout or "") + (r.stderr or "")
            if r.returncode == 0 or "SUCCESS" in blob:
                ended.append(n)
        except Exception:
            pass
    return ended


def stop_cua() -> dict:
    """Stop Cua driver. Binary may be renamed *.disabled-* (travel neutralize)."""
    out: dict = {"stopped": False, "killed_imgs": []}
    # Always kill by image name first (works even when exe renamed).
    for img in ("cua-driver.exe", "cua-driver-uia.exe", "AgentCursorOverlay.exe"):
        try:
            r = run(["taskkill", "/IM", img, "/F", "/T"], timeout=10)
            blob = ((r.stdout or "") + (r.stderr or "")).lower()
            if r.returncode == 0 or "success" in blob:
                out["killed_imgs"].append(img)
                out["stopped"] = True
        except Exception:
            pass
    exe = next((p for p in CUA_CANDIDATES if p.is_file()), None)
    if not exe:
        try:
            pkg = Path("C:/Users/CowNi/.cua-driver/packages/releases")
            if pkg.is_dir():
                found = sorted(pkg.glob("*/cua-driver.exe"), reverse=True)
                exe = found[0] if found else None
        except Exception:
            exe = None
    if not exe:
        out.setdefault("note", "exe_disabled_or_missing")
        return out
    try:
        r = run([str(exe), "stop"], timeout=15)
        out["rc"] = r.returncode
        out["msg"] = ((r.stdout or "") + (r.stderr or ""))[-200:]
        out["stopped"] = True
    except Exception as e:
        out["error"] = str(e)[:120]
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
    """Do NOT force-create focus_mode.STOP (operator owns via focus_mode.py).

    Silo STOP files are operator-owned via silo_ctl (Jeff clear/start).
    Writing silo_continuous/autonomous.STOP here froze land/depth for days
    after intentional unfreeze (2026-07-26 cook). Do not re-arm silo STOP.

    Also do not re-arm focus_mode.STOP every suppress tick - that disabled
    kitchen ticks (depth/watchdogs) during silo cook after operator focus off.
    Only refresh popup_emergency.STOP body if it already exists.
    """
    STATE.mkdir(parents=True, exist_ok=True)
    body = f"popup_storm_suppress {utc()}\n"
    # Never create focus_mode.STOP here. Operator: focus_mode.py on|off.
    emerg = STATE / "popup_emergency.STOP"
    if emerg.is_file():
        try:
            emerg.write_text(body, encoding="utf-8")
        except Exception:
            pass


def _shove_secure_uap_windows() -> int:
    """Hide + off-screen Secure UAP / permission dummy windows (Medium IL)."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        SW_HIDE = 0
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        HWND_BOTTOM = 1
        WM_CLOSE = 0x0010
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        tbuf = ctypes.create_unicode_buffer(512)
        cbuf = ctypes.create_unicode_buffer(256)
        n = [0]

        def _enum(hwnd, _lp):
            title = ""
            cls = ""
            try:
                user32.GetWindowTextW(hwnd, tbuf, 512)
                title = tbuf.value or ""
            except Exception:
                pass
            try:
                user32.GetClassNameW(hwnd, cbuf, 256)
                cls = cbuf.value or ""
            except Exception:
                pass
            blob = f"{title}|{cls}".lower()
            hit = (
                "secure uap" in blob
                or "requesting your permission" in blob
                or "user account control" in blob
                or cls == "$$$Secure UAP Dummy Window Class For Interim Dialog"
            )
            if not hit:
                return True
            try:
                user32.ShowWindow(hwnd, SW_HIDE)
                user32.SetWindowPos(
                    hwnd,
                    HWND_BOTTOM,
                    -32000,
                    -32000,
                    0,
                    0,
                    SWP_NOSIZE | SWP_NOACTIVATE,
                )
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                n[0] += 1
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)
        return n[0]
    except Exception:
        return 0


def kill_uac_consent() -> list[int]:
    """Best-effort kill consent.exe UAC dialogs (PowerShell requesting elevation).

    Secure Desktop / system-IL consent is Access-denied for Medium IL taskkill and
    WMIC ReturnValue=2. Never treat 'Method execution successful' as a kill ?
    only report PIDs actually gone after re-check. Also shove Secure-UAP dummy
    windows off-screen (hide alone is ignored by the secure class).
    """
    killed: list[int] = []
    pids: list[int] = []
    try:
        r = run(
            ["tasklist", "/FI", "IMAGENAME eq consent.exe", "/FO", "CSV", "/NH"],
            timeout=8,
        )
        for ln in (r.stdout or "").splitlines():
            # CSV: "consent.exe","1234",...
            parts = [p.strip().strip('"') for p in ln.split('","')]
            if not parts:
                continue
            name = parts[0].strip('"').lower()
            if name != "consent.exe":
                continue
            try:
                pids.append(int(parts[1]))
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    if not pids:
        try:
            for pid, name, _cmd in _list_processes():
                if (name or "").lower() == "consent.exe":
                    pids.append(pid)
        except Exception:
            pass

    # Always try to get the dummy windows out of the remote typing path first.
    try:
        _shove_secure_uap_windows()
    except Exception:
        pass

    for pid in pids:
        for cmd in (
            ["taskkill", "/PID", str(pid), "/F"],
            [
                "wmic",
                "process",
                "where",
                f"ProcessId={pid}",
                "call",
                "terminate",
            ],
        ):
            try:
                r = run(cmd, timeout=8)
                blob = ((r.stdout or "") + (r.stderr or "")).lower()
                # WMIC prints "Method execution successful" even on Access denied
                # (ReturnValue = 2). Only trust explicit success codes.
                if "returnvalue = 2" in blob or "access is denied" in blob:
                    continue
                if r.returncode == 0 and (
                    "returnvalue = 0" in blob
                    or "success" in blob
                    or "has been terminated" in blob
                ):
                    break
            except Exception:
                pass

    # Re-check which consent PIDs actually died.
    alive: set[int] = set()
    try:
        r = run(
            ["tasklist", "/FI", "IMAGENAME eq consent.exe", "/FO", "CSV", "/NH"],
            timeout=8,
        )
        for ln in (r.stdout or "").splitlines():
            parts = [p.strip().strip('"') for p in ln.split('","')]
            if len(parts) >= 2 and parts[0].strip('"').lower() == "consent.exe":
                try:
                    alive.add(int(parts[1]))
                except ValueError:
                    pass
    except Exception:
        alive = set(pids)
    for pid in pids:
        if pid not in alive:
            killed.append(pid)
    return killed


def kill_elevation_spawners() -> list[int]:
    """Kill powershell/cmd trying to elevate (RunAs / cua Highest / Admin bat).

    Root UAC source measured 2026-07-26:
      schtask cua-driver-serve RunLevel=HighestAvailable ?
      powershell -Command \"Start-Process ... cua-driver.exe serve\" ?
      consent.exe \"Windows PowerShell 5.1 is requesting your permission\"
    Also: Run-Popup-Kill-Admin-Once.REAL.bat (Verb RunAs).
    Kill spawners at Medium IL when still visible; consent itself needs Admin/user.
    """
    killed: list[int] = []
    elev_re = re.compile(
        r"(Verb\s+RunAs|Start-Process.*RunAs|Run-Popup-Kill-Admin|"
        r"Popup-Kill-Admin-Once|#Requires\s+-RunAsAdministrator|"
        r"cua-driver(?:-uia)?\.exe|"
        r"Start-Process.*cua-driver|"
        r"GPU\s*Tweak\s*III)",
        re.I,
    )
    for pid, name, cmd in _list_processes():
        nlow = (name or "").lower()
        if nlow not in ("powershell.exe", "pwsh.exe", "cmd.exe", "cua-driver.exe"):
            continue
        if not elev_re.search(cmd or "") and nlow != "cua-driver.exe":
            continue
        # never kill our own suppress shell if any
        if "popup_storm" in (cmd or "").lower():
            continue
        # never kill WT-hosted grok/work shells (bare powershell under Cascadia)
        if nlow in ("powershell.exe", "pwsh.exe") and not (cmd or "").strip():
            # bare cmd with no args is usually a WT tab ? leave it
            continue
        if nlow in ("powershell.exe", "pwsh.exe") and len((cmd or "").strip()) < 40:
            # bare path-only powershell under WT
            if "runas" not in (cmd or "").lower() and "cua" not in (cmd or "").lower():
                continue
        try:
            run(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=8)
            killed.append(pid)
        except Exception:
            pass
    return killed


def _list_processes() -> list[tuple[int, str, str]]:
    """Return (pid, name, cmdline) via WMIC (CREATE_NO_WINDOW ? no flash)."""
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
    """Kill bare powershell/python that steal focus (CUA/GPU/elevators).

    Under lockdown: do NOT kill Guardian/Bridge/Image-Rider/Loop trampolines ?
    they FreeConsole+exit 0 in <100ms. Force-kill made schtask Last Result
    267014 (TERMINATED) which Windows surfaces as an *error* popup.
    Still kill cua/GPU and elevators.
    """
    killed: list[int] = []
    me = os.getpid()
    lockdown = (STATE / "popup_lockdown.ON").is_file() or (
        STATE / "popup_emergency.STOP"
    ).is_file() or (STATE / "focus_mode.STOP").is_file()
    # Trampolines that self-exit 0 under lockdown ? never force-kill
    self_exit_re = re.compile(
        r"(Phronesis-Guardian|Ensure-Grok-Direct-Bridge|grok_hermes_loop|"
        r"Start-Image-Rider|Phronesis-OneButton-Start|Guardian-Body)",
        re.I,
    )
    for pid, name, cmd in _list_processes():
        if pid == me or pid <= 4:
            continue
        nlow = (name or "").lower()
        cmd_s = cmd or ""
        if nlow in (
            "gpu tweak iii.exe",
            "monitor.exe",
            "gt3 mobile service.exe",
        ):
            try:
                r = run(
                    [
                        "wmic",
                        "process",
                        "where",
                        f"ProcessId={pid}",
                        "call",
                        "terminate",
                    ],
                    timeout=10,
                )
                blob = ((r.stdout or "") + (r.stderr or "")).lower()
                if "returnvalue = 0" in blob or r.returncode == 0:
                    killed.append(pid)
                    continue
            except Exception:
                pass
            try:
                run(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=8)
                killed.append(pid)
            except Exception:
                pass
            continue
        if nlow not in (
            "powershell.exe",
            "pwsh.exe",
            "python.exe",
            "cmd.exe",
            "conhost.exe",
        ):
            if nlow in ("cua-driver.exe", "cua-driver-uia.exe"):
                pass
            else:
                continue
        if SAFE_CMD_RE.search(cmd_s):
            continue
        # Lockdown: leave self-exit trampolines alone
        if lockdown and self_exit_re.search(cmd_s):
            # Still kill if clearly elevating / cua start
            if not re.search(r"cua-driver|RunAs|GPU\s*Tweak", cmd_s, re.I):
                continue
        if not FLASHY_CMD_RE.search(cmd_s) and nlow not in (
            "cua-driver.exe",
            "cua-driver-uia.exe",
        ):
            continue
        try:
            run(["taskkill", "/PID", str(pid), "/F", "/T"], timeout=8)
            killed.append(pid)
        except Exception:
            pass
    return killed


def hide_visible_flash_windows(*, use_wmic: bool = False) -> int:
    """SW_HIDE flashy console + dummy GPU-tweak windows under focus mode.

    Default path is EnumWindows-only (cheap; safe every 1s). Optional WMIC
    pid map is only for full suppress() passes ? WMIC every 2s was freezing RDP.

    NEVER hides Windows Terminal / Cascadia (Grok Build typing surface).
    """
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        SW_HIDE = 0
        WM_CLOSE = 0x0010
        focus = (STATE / "focus_mode.STOP").is_file() or (
            STATE / "popup_emergency.STOP"
        ).is_file()
        flash_pids: set[int] = set()
        console_pids: set[int] = set()
        if use_wmic:
            for pid, name, cmd in _list_processes():
                nlow = (name or "").lower()
                if nlow in ("powershell.exe", "pwsh.exe", "python.exe", "cmd.exe"):
                    console_pids.add(pid)
                    if SAFE_CMD_RE.search(cmd or ""):
                        continue
                    if FLASHY_CMD_RE.search(cmd or "") or focus:
                        flash_pids.add(pid)
                if nlow in (
                    "gpu tweak iii.exe",
                    "monitor.exe",
                    "gpu_tweak_iii.exe",
                    "gt3 mobile service.exe",
                    "asusgpufanservice.exe",
                ):
                    flash_pids.add(pid)

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        hidden = [0]
        buf = ctypes.create_unicode_buffer(512)
        cbuf = ctypes.create_unicode_buffer(256)

        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title = ""
            cls = ""
            try:
                user32.GetWindowTextW(hwnd, buf, 512)
                title = buf.value or ""
            except Exception:
                title = ""
            try:
                user32.GetClassNameW(hwnd, cbuf, 256)
                cls = cbuf.value or ""
            except Exception:
                cls = ""
            # Hard protect: Windows Terminal / Grok Build must stay typeable under RDP.
            if cls and PROTECT_CLASS_RE.search(cls):
                return True
            if title and PROTECT_TITLE_RE.search(title):
                return True
            kill = False
            if pid.value in flash_pids:
                if cls and PROTECT_CLASS_RE.search(cls):
                    return True
                kill = True
            elif title and FLASHY_TITLE_RE.search(title):
                kill = True
            elif focus and title and BARE_CONSOLE_TITLE_RE.search(title):
                if cls and PROTECT_CLASS_RE.search(cls):
                    return True
                kill = True
            # Always snuff GPU Tweak dummy windows (even without focus STOP)
            elif title and re.search(r"SOUI_DUMMY|GPU\s*Tweak", title, re.I):
                kill = True
            if kill:
                user32.ShowWindow(hwnd, SW_HIDE)
                # Close error dialogs only (not Terminal)
                if title and re.search(r"Application Error|tasklist\.exe", title, re.I):
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                hidden[0] += 1
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)
        try:
            hidden[0] += _shove_secure_uap_windows()
        except Exception:
            pass
        return hidden[0]
    except Exception:
        return 0


def restore_protected_work_windows() -> int:
    """If focus mode is on, un-minimize Grok Build / Cascadia work terminals.

    Does NOT force foreground every tick (that steals typing). Only SW_RESTORE
    when IsIconic. Cheap EnumWindows; safe every 1s from storm daemon.
    """
    if sys.platform != "win32":
        return 0
    focus = (STATE / "focus_mode.STOP").is_file() or (
        STATE / "popup_emergency.STOP"
    ).is_file()
    if not focus:
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        restored = [0]
        buf = ctypes.create_unicode_buffer(512)
        cbuf = ctypes.create_unicode_buffer(256)
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd, _lp):
            if not user32.IsWindow(hwnd):
                return True
            try:
                user32.GetClassNameW(hwnd, cbuf, 256)
                cls = cbuf.value or ""
                user32.GetWindowTextW(hwnd, buf, 512)
                title = buf.value or ""
            except Exception:
                return True
            protect = False
            if cls and PROTECT_CLASS_RE.search(cls):
                # Only restore grok-named Cascadia frames, or sole titled work tabs.
                if title and (
                    PROTECT_TITLE_RE.search(title)
                    or re.search(r"\bgrok\b", title, re.I)
                ):
                    protect = True
            elif title and re.search(r"\bgrok\b", title, re.I):
                protect = True
            if protect and user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
                restored[0] += 1
            return True

        user32.EnumWindows(WNDENUMPROC(_enum), 0)
        return restored[0]
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
        "uac_consent_gone": kill_uac_consent(),
        "elevators_killed": kill_elevation_spawners(),
        "killed_flashy": kill_flashy_console_procs(),
        "hidden_windows": hide_visible_flash_windows(use_wmic=True),
        # Do NOT kill sovereign_openai_proxy ? dual-proxy thrash left :8091 dead.
        "killed_dup_dash": dedup_pythonw(r"dashboard --port 9119"),
        "killed_orphan_comfy": kill_orphan_comfy_dup(),
    }
    try:
        sys.path.insert(0, str(SCRIPTS))
        from no_popup_law import ensure_hidden_twins_enabled, quiet_user_ticks

        # Prefer silent pythonw Hidden twins; quiet non-essential user ticks.
        rep["hidden_twins"] = ensure_hidden_twins_enabled()
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
    # Prefer home pythonw ? venv Scripts\\pythonw trampolines and dual-starts.
    pyw = Path(r"C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe")
    if not pyw.is_file():
        pyw = Path(r"D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe")
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
